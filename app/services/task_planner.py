"""Day4 Plan-Solve 任务规划 Agent — 任务拆解、调度、并行执行、重试、汇总。

核心流程：
  用户复杂提问
  → Plan：模型拆解结构化子任务列表
  → 调度器循环/并行执行每个子任务
    - 子任务=工具调用：调用 Function Calling 工具
    - 子任务=知识库查询：执行 RAG 检索
    - 子任务=文本推理：直接 LLM 生成
  → 缓存所有子任务执行结果
  → LLM 汇总全部子任务输出，生成最终完整回答

"""
import asyncio
import json
import logging
import re
import time
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field

from app.services.deepseek import AIService
from app.services.tools import registry, all_tool_schemas
from app.services.indexer import Indexer

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# 1. 子任务结构化 Schema
# ═══════════════════════════════════════════════════════════════════

class SubTask(BaseModel):
    """单个子任务定义。"""
    task_id: str = Field(description="任务唯一 ID，如 t1/t2/t3")
    task_type: str = Field(
        description="任务类型：tool（调用工具）/ rag_search（知识库检索）/ llm_summary（文本推理）"
    )
    content: str = Field(description="任务执行入参，工具调用填参数描述，rag 填查询词，推理填提示词")
    tool_name: str = Field(default="", description="当 task_type=tool 时，指定工具名称")
    rely_task_ids: List[str] = Field(default_factory=list, description="依赖的前置任务 ID，无依赖为空")


class TaskPlan(BaseModel):
    """完整任务计划。"""
    task_list: List[SubTask] = Field(description="完整子任务列表")


# ═══════════════════════════════════════════════════════════════════
# 2. 任务执行缓存与调度器
# ═══════════════════════════════════════════════════════════════════

class TaskScheduler:
    """通用任务调度器：状态管理、依赖判断、串行/并行执行、失败重试。"""

    def __init__(self, ai: AIService, db=None):
        self.ai = ai
        self.db = db
        self.task_cache: Dict[str, Dict] = {}  # {task_id: {info, status, result, retry_count}}
        self.max_retry = 2  # 单任务最大重试次数

    def init_tasks(self, task_list: List[SubTask]):
        """初始化任务缓存，所有任务状态为 pending。"""
        self.task_cache.clear()
        for task in task_list:
            self.task_cache[task.task_id] = {
                "info": task,
                "status": "pending",
                "result": "",
                "retry_count": 0,
            }
        logger.info(f"[scheduler] initialized {len(task_list)} tasks: "
                    f"{[(t.task_id, t.task_type) for t in task_list]}")

    def is_rely_finish(self, task: SubTask) -> bool:
        """检查依赖任务是否全部完成（success 或 failed 都算完成）。"""
        for tid in task.rely_task_ids:
            item = self.task_cache.get(tid)
            if not item or item["status"] not in ("success", "failed"):
                return False
        return True

    async def run_single_task(self, task: SubTask) -> str:
        """执行单个子任务。"""
        if task.task_type == "tool":
            return await self._run_tool_task(task)
        elif task.task_type == "rag_search":
            return await self._run_rag_task(task)
        elif task.task_type == "llm_summary":
            return await self._run_llm_task(task)
        else:
            return f"不支持的任务类型：{task.task_type}"

    async def _run_tool_task(self, task: SubTask) -> str:
        """调用工具执行任务。"""
        tool_name = task.tool_name
        tool = registry.get(tool_name)
        if tool is None:
            available = list(registry.names())
            return f"错误：工具 '{tool_name}' 不存在。可用工具：{available}"

        # 让 LLM 解析 content 为工具参数
        tool_schema = tool.schema()
        prompt = f"""你是一个工具调用解析器。根据用户指令，提取工具调用参数。

工具名称: {tool_name}
工具描述: {tool.description}
工具参数 Schema: {json.dumps(tool.parameters, ensure_ascii=False)}

用户指令: {task.content}

请输出 JSON 格式的工具调用参数，仅输出 JSON，不要其他文字：
{{"参数名": "参数值", ...}}"""

        try:
            raw = await self.ai.call_model(prompt)
            json_str = self._extract_json(raw)
            args = json.loads(json_str)
            logger.info(f"[scheduler] tool '{tool_name}' args: {args}")
            result = await tool.execute(**args)
            return result
        except Exception as e:
            logger.error(f"[scheduler] tool '{tool_name}' failed: {e}")
            return f"工具执行失败：{str(e)}"

    async def _run_rag_task(self, task: SubTask) -> str:
        """知识库检索任务。"""
        try:
            indexer = Indexer(self.db) if self.db else None
            if indexer is None:
                return "知识库未初始化，无法检索"
            results = indexer.search_chunks(task.content, top_k=3)
            if not results:
                return f"知识库中未找到与 '{task.content}' 相关的内容"
            parts = []
            for i, r in enumerate(results):
                src = r.get("filename", "unknown")
                sim = r.get("similarity", 0)
                parts.append(f"[来源{i+1}: {src} | 相似度: {sim:.2f}]\n{r['content']}")
            return "\n\n---\n\n".join(parts)
        except Exception as e:
            logger.error(f"[scheduler] rag_search failed: {e}")
            return f"知识库检索失败：{str(e)}"

    async def _run_llm_task(self, task: SubTask) -> str:
        """纯文本推理任务。"""
        try:
            result = await self.ai.call_model(task.content)
            return result
        except Exception as e:
            logger.error(f"[scheduler] llm_summary failed: {e}")
            return f"文本推理失败：{str(e)}"

    async def run_all_tasks(self) -> str:
        """批量调度执行所有任务（支持并行执行无依赖任务）。

        返回汇总文本。
        """
        all_task_ids = list(self.task_cache.keys())
        finished = set()
        round_num = 0

        while len(finished) < len(all_task_ids):
            round_num += 1
            # 找出本轮可执行的任务（pending + 依赖全部完成）
            ready_tasks = []
            for tid in all_task_ids:
                if tid in finished:
                    continue
                item = self.task_cache[tid]
                if item["status"] != "pending":
                    continue
                task_info = item["info"]
                if not self.is_rely_finish(task_info):
                    continue
                ready_tasks.append(tid)

            if not ready_tasks:
                # 没有可执行的任务，检查是否有死锁
                pending_ids = [tid for tid in all_task_ids if tid not in finished
                               and self.task_cache[tid]["status"] == "pending"]
                if pending_ids:
                    logger.warning(f"[scheduler] deadlock detected: pending tasks {pending_ids} "
                                   f"have unmet dependencies")
                    # 标记所有死锁任务为 failed
                    for tid in pending_ids:
                        self.task_cache[tid]["status"] = "failed"
                        self.task_cache[tid]["result"] = "任务因依赖未满足而跳过"
                        finished.add(tid)
                break

            # 区分独立任务和依赖任务
            independent = [tid for tid in ready_tasks
                           if not self.task_cache[tid]["info"].rely_task_ids]
            dependent = [tid for tid in ready_tasks if tid not in set(independent)]

            logger.info(f"[scheduler] round {round_num}: independent={independent}, dependent={dependent}")

            # 并行执行所有独立任务
            if independent:
                await self._execute_batch(independent, finished)

            # 串行执行依赖任务（保守策略，确保顺序正确）
            for tid in dependent:
                await self._execute_single(tid)
                finished.add(tid)

            # 防止无限循环
            if round_num > 10:
                logger.warning("[scheduler] max rounds reached, forcing finish")
                for tid in all_task_ids:
                    if tid not in finished:
                        self.task_cache[tid]["status"] = "failed"
                        self.task_cache[tid]["result"] = "超过最大执行轮次，任务被跳过"
                        finished.add(tid)
                break

        # 汇总所有任务结果
        return self._build_summary()

    async def _execute_batch(self, task_ids: List[str], finished: set):
        """并行执行一批独立任务。"""
        logger.info(f"[scheduler] parallel executing {len(task_ids)} tasks: {task_ids}")
        tasks = []
        for tid in task_ids:
            self.task_cache[tid]["status"] = "running"
            tasks.append(self._execute_single(tid))

        await asyncio.gather(*tasks)
        for tid in task_ids:
            finished.add(tid)

    async def _execute_single(self, task_id: str):
        """执行单个任务（含重试逻辑）。"""
        item = self.task_cache[task_id]
        task_info = item["info"]
        item["status"] = "running"
        t0 = time.time()

        for attempt in range(self.max_retry + 1):
            try:
                result = await self.run_single_task(task_info)
                item["result"] = result
                item["status"] = "success"
                elapsed = time.time() - t0
                logger.info(f"[scheduler] {task_id} ({task_info.task_type}) success: "
                            f"{len(result)} chars, elapsed={elapsed:.1f}s, attempts={attempt+1}")
                return
            except Exception as e:
                item["retry_count"] += 1
                logger.warning(f"[scheduler] {task_id} attempt {attempt+1}/{self.max_retry+1} failed: {e}")
                if attempt < self.max_retry:
                    await asyncio.sleep(1)  # 短暂等待后重试
                else:
                    item["status"] = "failed"
                    item["result"] = f"任务执行失败（已重试 {self.max_retry} 次）：{str(e)}"
                    elapsed = time.time() - t0
                    logger.error(f"[scheduler] {task_id} final fail after {self.max_retry+1} attempts, "
                                 f"elapsed={elapsed:.1f}s")

    def _build_summary(self) -> str:
        """构建任务执行汇总。"""
        parts = []
        for tid in sorted(self.task_cache.keys()):
            item = self.task_cache[tid]
            task_info = item["info"]
            status_icon = {"success": "✅", "failed": "❌", "pending": "⏳", "running": "🔄"}.get(
                item["status"], "❓")
            parts.append(
                f"### {status_icon} [{tid}] {task_info.task_type}"
                f"{' → ' + task_info.tool_name if task_info.tool_name else ''}\n"
                f"**状态**: {item['status']} | **重试**: {item['retry_count']}次\n\n"
                f"{item['result'][:1000]}\n"  # 限制单任务结果长度
            )
        return "\n\n".join(parts)

    @staticmethod
    def _extract_json(text: str) -> str:
        """从文本中提取 JSON 字符串。"""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return match.group()
        return text


# ═══════════════════════════════════════════════════════════════════
# 3. Plan-Solve 规划器
# ═══════════════════════════════════════════════════════════════════

class TaskPlanner:
    """Plan-Solve 任务规划器：拆解 → 调度 → 执行 → 汇总。

    整合 LLM + Function Calling + RAG + 任务规划，完成全能基础智能体。
    """

    def __init__(self, db=None, ai: AIService = None):
        self.db = db
        self.ai = ai or AIService()
        self.scheduler = TaskScheduler(self.ai, self.db)
        self.max_plan_round = 5

        # 获取可用工具列表
        self._available_tools = list(registry.all_tools())
        self._tool_descriptions = self._build_tool_descriptions()

    def _build_tool_descriptions(self) -> str:
        """构建工具列表描述文本。"""
        if not self._available_tools:
            return "暂无可用工具"
        lines = []
        for t in self._available_tools:
            lines.append(f"- **{t.name}**: {t.description}")
        return "\n".join(lines)

    def _build_plan_prompt(self, user_query: str) -> str:
        """构建规划 Prompt。"""
        schema = TaskPlan.model_json_schema()
        return f"""你是任务拆解专家，将用户复杂问题拆分为子任务列表，严格输出 JSON，禁止多余文字。

## 可用工具
{self._tool_descriptions}

## 支持的任务类型
1. **tool** — 调用工具。需指定 tool_name（工具名）和 content（参数描述，LLM 会自动解析参数）
2. **rag_search** — 知识库检索。content 填检索关键词
3. **llm_summary** — 纯文本推理/总结。content 填推理提示词

## 规则
1. 有先后依赖关系必须填写 rely_task_ids（如：先计算再汇总）
2. 无依赖的任务填空数组 []，可并行执行
3. 简单无需拆分的单一问题，只生成 1 条 llm_summary 任务
4. 工具调用时，content 描述需要什么参数和值（如 "计算 125+36"）
5. 输出格式严格遵循以下 JSON Schema，不要输出其他文字：

```json
{schema}
```

用户问题：{user_query}"""

    async def create_plan(self, user_query: str) -> TaskPlan:
        """生成任务计划。失败时自动重试一次。"""
        logger.info(f"[planner] creating plan for: {user_query[:120]}...")
        prompt = self._build_plan_prompt(user_query)
        t0 = time.time()

        for attempt in range(2):
            try:
                raw = await self.ai.call_model(prompt)
                json_str = self.scheduler._extract_json(raw)
                plan = TaskPlan.model_validate_json(json_str)
                elapsed = time.time() - t0
                logger.info(f"[planner] plan created: {len(plan.task_list)} tasks, "
                            f"elapsed={elapsed:.1f}s, attempt={attempt+1}")
                for t in plan.task_list:
                    logger.info(f"[planner]   {t.task_id}: type={t.task_type}, "
                                f"tool={t.tool_name or 'N/A'}, "
                                f"deps={t.rely_task_ids or '[]'}, "
                                f"content={t.content[:80]}...")
                return plan
            except Exception as e:
                logger.warning(f"[planner] plan parse failed (attempt {attempt+1}): {e}")
                if attempt == 0:
                    logger.info("[planner] retrying plan creation...")
                else:
                    raise Exception(f"任务规划 JSON 解析失败（已重试）: {e}")

    async def run_full_agent(self, user_query: str, chat_history: List[dict] = None) -> dict:
        """完整 Plan-Solve 流程：规划 → 执行 → 汇总。

        Args:
            user_query: 用户原始问题
            chat_history: 对话历史

        Returns:
            dict with keys: user_query, task_list, task_detail, task_raw_summary, final_answer
        """
        t0 = time.time()
        logger.info(f"[planner] ====== Plan-Solve Agent Start ======")
        logger.info(f"[planner] query: {user_query[:120]}...")

        # 1. 生成任务清单
        logger.info(f"[planner] --- Phase 1: Plan ---")
        plan = await self.create_plan(user_query)
        if not plan.task_list:
            # 空计划，直接回答
            logger.info("[planner] empty plan, direct answer")
            answer = await self.ai.call_model(user_query)
            return {
                "user_query": user_query,
                "task_list": [],
                "task_detail": {},
                "task_raw_summary": "",
                "final_answer": answer,
            }

        # 2. 调度器初始化任务
        logger.info(f"[planner] --- Phase 2: Execute ({len(plan.task_list)} tasks) ---")
        self.scheduler.init_tasks(plan.task_list)

        # 3. 执行所有子任务
        task_summary = await self.scheduler.run_all_tasks()
        elapsed_exec = time.time() - t0
        logger.info(f"[planner] execution done, elapsed={elapsed_exec:.1f}s")

        # 统计执行结果
        success_count = sum(1 for v in self.scheduler.task_cache.values()
                            if v["status"] == "success")
        failed_count = sum(1 for v in self.scheduler.task_cache.values()
                           if v["status"] == "failed")
        logger.info(f"[planner] tasks: {success_count} success, {failed_count} failed")

        # 4. LLM 整合所有子任务输出最终回答
        logger.info(f"[planner] --- Phase 3: Summarize ---")
        final_prompt = f"""用户原始问题：{user_query}

各子任务执行结果：
{task_summary}

基于以上所有任务结果，整合输出完整通顺的最终答案。
要求：
- 综合所有子任务结果，不要遗漏
- 有计算结果要展示
- 有知识库内容要引用
- 有失败任务要说明
- 用中文，结构清晰，专业简洁"""

        final_answer = await self.ai.call_model(final_prompt)
        elapsed_total = time.time() - t0
        logger.info(f"[planner] final answer: {len(final_answer)} chars, total_elapsed={elapsed_total:.1f}s")
        logger.info(f"[planner] ====== Plan-Solve Agent End ======")

        # 构建任务详情（用于前端展示）
        task_detail = {}
        for tid, item in self.scheduler.task_cache.items():
            task_info = item["info"]
            task_detail[tid] = {
                "task_id": tid,
                "task_type": task_info.task_type,
                "tool_name": task_info.tool_name,
                "content": task_info.content,
                "rely_task_ids": task_info.rely_task_ids,
                "status": item["status"],
                "result": item["result"][:500],
                "retry_count": item["retry_count"],
            }

        return {
            "user_query": user_query,
            "task_list": [t.model_dump() for t in plan.task_list],
            "task_detail": task_detail,
            "task_raw_summary": task_summary,
            "final_answer": final_answer,
            "elapsed": f"{elapsed_total:.1f}s",
        }
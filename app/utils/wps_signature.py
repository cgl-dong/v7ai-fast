import hashlib
from datetime import datetime, timezone
from typing import Dict, Optional


class WPS3Signature:
    HTTP_HEADER_AUTHORIZATION = "X-Auth"
    HTTP_HEADER_DATE = "Date"
    HTTP_HEADER_CONTENT_MD5 = "Content-Md5"
    HTTP_HEADER_CONTENT_TYPE = "Content-Type"

    def __init__(self, app_id: str, secret_key: str):
        self.app_id = app_id
        self.secret_key = secret_key

    def get_content_md5(self, content: str) -> str:
        if not content:
            return hashlib.md5(b"").hexdigest()
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def get_gmt_date_string(self) -> str:
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    def get_signature(self, uri_with_querystring: str, content_md5: str, date_string: str, content_type: str) -> str:
        sha1 = hashlib.sha1()
        sha1.update(self.secret_key.encode("utf-8"))
        sha1.update(content_md5.encode("utf-8"))
        sha1.update(uri_with_querystring.encode("utf-8"))
        sha1.update(content_type.encode("utf-8"))
        sha1.update(date_string.encode("utf-8"))
        return sha1.hexdigest()

    def get_authorization(self, uri_with_querystring: str, content_md5: str, date_string: str, content_type: str) -> str:
        signature = self.get_signature(uri_with_querystring, content_md5, date_string, content_type)
        return f"WPS-3:{self.app_id}:{signature}"

    def get_signature_headers(self, uri_with_querystring: str, content: str = "", content_type: str = "application/json") -> Dict[str, str]:
        if uri_with_querystring is None:
            uri_with_querystring = ""
        if content is None:
            content = ""

        content_md5 = self.get_content_md5(content)
        date_string = self.get_gmt_date_string()
        authorization = self.get_authorization(uri_with_querystring, content_md5, date_string, content_type)

        return {
            self.HTTP_HEADER_AUTHORIZATION: authorization,
            self.HTTP_HEADER_CONTENT_TYPE: content_type,
            self.HTTP_HEADER_DATE: date_string,
            self.HTTP_HEADER_CONTENT_MD5: content_md5
        }

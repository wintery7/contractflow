"""Pydantic 모델 → OpenAI Structured Outputs(strict) 호환 JSON 스키마.

strict 모드 규칙:
- 모든 object에 additionalProperties: false
- 모든 속성이 required (선택 값은 required이되 null 허용으로 표현)
- default 등 일부 키워드 미지원

SDK의 비공개 변환 함수에 의존하지 않고 직접 변환해 공급자 SDK 버전 변화에 덜 흔들리게 한다.
"""

import copy
from typing import Any

from pydantic import BaseModel

# strict 모드에서 지원되지 않거나 모델 출력을 불필요하게 제한할 수 있는 키워드
_UNSUPPORTED_KEYS = {"default", "format", "minLength", "maxLength", "minimum", "maximum"}


def _strictify(node: Any) -> Any:
    if isinstance(node, list):
        return [_strictify(item) for item in node]
    if not isinstance(node, dict):
        return node

    result = {key: _strictify(value) for key, value in node.items() if key not in _UNSUPPORTED_KEYS}
    if result.get("type") == "object" and "properties" in result:
        result["additionalProperties"] = False
        result["required"] = list(result["properties"].keys())
    return result


def to_strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """길이·범위 같은 세부 제약은 스키마에서 빼고, 응답을 받은 뒤 Pydantic이 다시 검증한다."""
    return _strictify(copy.deepcopy(model.model_json_schema()))

"""PTL 错误包装单测：Anthropic/OpenAI prompt_too_long 被正确包装（T20.5）。"""

from Alincode.client import PromptTooLongError, _wrap_anthropic_ptl, _wrap_openai_ptl


def _make_anthropic_ptl():
    """模拟 Anthropic BadRequestError（prompt too long）。"""
    class FakeBadRequestError(Exception):
        pass
    e = FakeBadRequestError("prompt is too long: maximum context length is 200000 tokens. your request used 220000 tokens")
    return e


def _make_openai_ptl():
    """模拟 OpenAI BadRequestError（context_length_exceeded）。"""
    class FakeBadRequestError(Exception):
        pass
    e = FakeBadRequestError("Error code: 400 - context_length_exceeded. Maximum context length is 128000 tokens")
    return e


def _make_other_error():
    """非 PTL 错误（500）。"""
    class FakeServerError(Exception):
        pass
    return FakeServerError("internal server error")


def test_anthropic_wraps_prompt_too_long():
    """Anthropic PTL 被包装为 PromptTooLongError。"""
    e = _make_anthropic_ptl()
    wrapped = _wrap_anthropic_ptl(e)
    assert isinstance(wrapped, PromptTooLongError)
    assert wrapped.__cause__ is e


def test_openai_wraps_prompt_too_long():
    """OpenAI context_length_exceeded 被包装为 PromptTooLongError。"""
    e = _make_openai_ptl()
    wrapped = _wrap_openai_ptl(e)
    assert isinstance(wrapped, PromptTooLongError)
    assert wrapped.__cause__ is e


def test_anthropic_other_error_not_wrapped():
    """非 PTL 异常不包装。"""
    e = _make_other_error()
    wrapped = _wrap_anthropic_ptl(e)
    assert not isinstance(wrapped, PromptTooLongError)
    assert wrapped is e


def test_openai_other_error_not_wrapped():
    """非 PTL 异常不包装。"""
    e = _make_other_error()
    wrapped = _wrap_openai_ptl(e)
    assert not isinstance(wrapped, PromptTooLongError)
    assert wrapped is e


def test_ptl_message_distinction():
    """提示词超长与普通 BadRequest 可区分。"""
    ptl = PromptTooLongError("custom message")
    other = Exception("some other error")
    assert isinstance(ptl, PromptTooLongError)
    assert not isinstance(other, PromptTooLongError)

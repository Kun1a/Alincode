"""Conversation 单测：replace_messages 深拷贝 + None 安全（T23）。"""

from Alincode.conversation import ConversationManager, Message


def test_replace_messages_deep_copy():
    """replace_messages 后修改原列表不影响 conv。"""
    conv = ConversationManager()
    conv.add_user("hello")
    msgs = [Message(role="user", content="replaced")]
    conv.replace_messages(msgs)
    # 修改原列表
    msgs[0] = Message(role="assistant", content="hacked")
    result = conv.messages
    assert len(result) == 1
    assert result[0].role == "user"
    assert result[0].content == "replaced"


def test_replace_messages_empty():
    """传空列表不抛异常。"""
    conv = ConversationManager()
    conv.add_user("hello")
    conv.replace_messages([])
    assert conv.length() == 0


def test_replace_messages_none():
    """传 None 不抛异常，messages 为空。"""
    conv = ConversationManager()
    conv.replace_messages(None)
    assert conv.length() == 0


def test_length():
    """length() 返回消息列表长度。"""
    conv = ConversationManager()
    assert conv.length() == 0
    conv.add_user("hi")
    assert conv.length() == 1

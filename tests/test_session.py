"""会话持久化测试：JSONL 读写、列表、恢复、清理（T8）。"""

import datetime
import json
import time

from Alincode.conversation import Message
from Alincode.session.writer import Writer
from Alincode.session.load import load_session, _truncate_orphaned_tool_calls
from Alincode.session.list import list_sessions
from Alincode.session.cleanup import clean_expired


def test_writer_append_and_read(tmp_path):
    """写入消息 → 读回验证。"""
    w = Writer(str(tmp_path))
    msg = Message(role="user", content="hello")
    w.append(msg, model="test-model", is_first=True)
    w.close()

    jsonl = tmp_path / "conversation.jsonl"
    lines = jsonl.read_text().strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["role"] == "user"
    assert data["content"] == "hello"
    assert data["model"] == "test-model"


def test_writer_compact_marker(tmp_path):
    """compact 标记 → load_session 只返回标记后内容。"""
    w = Writer(str(tmp_path))
    w.append(Message(role="user", content="旧消息"), is_first=True)
    w.write_compact_marker()
    w.append(Message(role="user", content="新消息"))
    w.append(Message(role="assistant", content="回复"))
    w.close()

    msgs = load_session(str(tmp_path))
    assert len(msgs) == 2
    assert msgs[0].content == "新消息"


def test_load_session_bad_line_skip(tmp_path):
    """坏行被跳过。"""
    jsonl = tmp_path / "conversation.jsonl"
    with open(jsonl, "w", encoding="utf-8") as f:
        f.write('{"role":"user","content":"ok","ts":1000}\n')
        f.write('{invalid json\n')
        f.write('{"role":"assistant","content":"hi","ts":1001}\n')

    msgs = load_session(str(tmp_path))
    assert len(msgs) == 2


def test_truncate_orphaned_tool_calls():
    """末尾孤立 tool_calls 被截断。"""
    from Alincode.conversation import ToolCall
    msgs = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="", tool_calls=[ToolCall(id="1", name="read", input="{}")]),
    ]
    result = _truncate_orphaned_tool_calls(msgs)
    assert len(result) == 1
    assert result[0].role == "user"


def test_list_sessions(tmp_path):
    """扫描会话目录 → 返回列表。"""
    import secrets
    now = datetime.datetime.now()
    sid1 = now.strftime("%Y%m%d-%H%M%S") + f"-{secrets.token_hex(2)}"
    sid2 = (now.replace(minute=(now.minute + 1) % 60)).strftime("%Y%m%d-%H%M%S") + f"-{secrets.token_hex(2)}"
    for sid in [sid1, sid2]:
        sd = tmp_path / sid
        sd.mkdir(parents=True)
        with open(sd / "conversation.jsonl", "w", encoding="utf-8") as f:
            f.write('{"role":"user","content":"test message","ts":1000,"model":"gpt"}\n')
        time.sleep(0.01)
    sessions = list_sessions(str(tmp_path))
    assert len(sessions) == 2
    assert sessions[0].title == "test message"


def test_list_sessions_skips_old_format(tmp_path):
    """旧格式 ID 目录被跳过。"""
    old_dir = tmp_path / "1717000000-abc12345"
    old_dir.mkdir()
    (old_dir / "conversation.jsonl").write_text('{"role":"user","content":"old","ts":1000}\n')

    sessions = list_sessions(str(tmp_path))
    assert len(sessions) == 0


def test_clean_expired(tmp_path):
    """过期会话被清理。"""
    now = datetime.datetime.now()
    old_ts = (now - datetime.timedelta(days=31)).strftime("%Y%m%d-%H%M%S") + "-a1b2"
    new_ts = (now - datetime.timedelta(days=1)).strftime("%Y%m%d-%H%M%S") + "-c3d4"
    for sid in [old_ts, new_ts]:
        sd = tmp_path / sid
        sd.mkdir(parents=True)
        (sd / "conversation.jsonl").write_text('{"role":"user","content":"x","ts":1000}\n')

    clean_expired(str(tmp_path), max_age=datetime.timedelta(days=30))
    assert not (tmp_path / old_ts).exists()
    assert (tmp_path / new_ts).exists()

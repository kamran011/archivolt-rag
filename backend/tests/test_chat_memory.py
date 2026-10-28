from app.domains.chat.memory import build_memory
from app.domains.rag.prompts import build_context_prompt
from app.providers.llm.base import LLMResponse


class FakeLLM:
    def __init__(self, content="summary v1", error=None):
        self.content, self.error = content, error
        self.calls: list[str] = []

    async def generate(self, messages, temperature=0.1, max_tokens=2048):
        self.calls.append(messages[0]["content"])
        if self.error:
            raise self.error
        return LLMResponse(
            content=self.content, prompt_tokens=10, completion_tokens=5,
            model="fake", finish_reason="stop",
        )


def turns(n: int) -> list[dict]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(n)
    ]


async def test_short_conversation_is_verbatim_with_no_llm_call():
    llm = FakeLLM()
    mem = await build_memory(turns(8), None, 0, llm, window=10, batch=6)
    assert mem.recent == turns(8)
    assert mem.summary is None and mem.summarized_count == 0
    assert llm.calls == []


async def test_waits_for_a_full_batch_and_keeps_the_overflow_verbatim():
    llm = FakeLLM()
    # 15 turns, window 10 -> 5 older turns waiting, below the batch of 6.
    mem = await build_memory(turns(15), None, 0, llm, window=10, batch=6)
    assert llm.calls == []
    assert mem.recent == turns(15)  # nothing dropped between summary and buffer


async def test_folds_older_turns_into_the_summary():
    llm = FakeLLM("user asked about refunds")
    mem = await build_memory(turns(16), None, 0, llm, window=10, batch=6)
    assert len(llm.calls) == 1
    assert "m0" in llm.calls[0] and "m5" in llm.calls[0] and "m6" not in llm.calls[0]
    assert mem.summary == "user asked about refunds"
    assert mem.summarized_count == 6
    assert mem.recent == turns(16)[6:]


async def test_extends_the_previous_summary_with_only_new_turns():
    llm = FakeLLM("v2")
    mem = await build_memory(turns(22), "v1", 6, llm, window=10, batch=6)
    assert "v1" in llm.calls[0]
    assert "m5:" not in llm.calls[0] and "m6" in llm.calls[0] and "m11" in llm.calls[0]
    assert (mem.summary, mem.summarized_count) == ("v2", 12)
    assert mem.recent == turns(22)[12:]


async def test_failed_summary_keeps_old_state_and_bounds_the_prompt():
    llm = FakeLLM(error=RuntimeError("provider down"))
    mem = await build_memory(turns(40), "v1", 6, llm, window=10, batch=6)
    assert (mem.summary, mem.summarized_count) == ("v1", 6)
    assert mem.recent == turns(40)[-16:]


async def test_disabled_falls_back_to_sliding_window():
    mem = await build_memory(turns(30), "stale", 12, None, window=10, batch=6)
    assert mem.recent == turns(30)[-10:]
    assert mem.summary is None


async def test_count_past_the_end_does_not_hide_every_turn():
    mem = await build_memory(turns(4), "v1", 50, FakeLLM(), window=10, batch=6)
    assert mem.recent == turns(4)
    assert (mem.summary, mem.summarized_count) == (None, 0)


def test_summary_goes_into_the_system_prompt_as_non_citable_background():
    prompt = build_context_prompt("[Source 1] x", "user is comparing plans")
    assert "user is comparing plans" in prompt
    assert "NOT an evidence source" in prompt
    assert "Summary of the earlier" not in build_context_prompt("[Source 1] x")

"""Uji token-tiering SaaS — batas per tier diklamp ceiling hardware HIRO."""
from app.config import TIER_TOKEN_LIMITS, get_context_budget, hw


def test_tier_caps_documented():
    assert TIER_TOKEN_LIMITS["free"]["num_ctx"] == 2048
    assert TIER_TOKEN_LIMITS["premium_l1"]["num_ctx"] == 8192
    assert TIER_TOKEN_LIMITS["premium_l2"]["num_ctx"] == 16384


def test_budget_clamped_by_hardware():
    for tier, caps in TIER_TOKEN_LIMITS.items():
        b = get_context_budget(tier)
        assert b["num_ctx"] == min(caps["num_ctx"], hw.ollama_num_ctx)
        assert b["num_predict"] == min(caps["num_predict"], hw.ollama_num_predict)


def test_free_tier_never_exceeds_2048():
    b = get_context_budget("free")
    assert b["num_ctx"] <= 2048


def test_unknown_tier_falls_back_to_free():
    assert get_context_budget("platinum") == get_context_budget("free")


def test_premium_capped_on_low_vram():
    # Pada 2x GTX 1050 Ti (VRAM ~4GB): ceiling per-GPU = 4096
    if hw.ollama_num_ctx <= 4096:
        assert get_context_budget("premium_l2")["num_ctx"] <= 4096

"""One test per row of story 2.1's I/O & Edge-Case Matrix.

Tests focus on the agent's offline seams: model builder, prompt builder,
decision extractor. No test makes a network call or requires app.db.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from agent import _build_model, _build_prompt, _extract_decision


class TestModelBuilder:
    """Test the model builder for provider switching."""

    def test_provider_default_is_gemini(self):
        """Provider unset -> ChatGoogleGenerativeAI with default model."""
        # Clear any PROVIDER env var
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PROVIDER", None)
            os.environ.pop("MODEL", None)

            model = _build_model()

            from langchain_google_genai import ChatGoogleGenerativeAI
            assert isinstance(model, ChatGoogleGenerativeAI)
            assert model.model == "gemini-3.8-flash"

    def test_provider_gemini_with_default_model(self):
        """PROVIDER=gemini (explicit) -> ChatGoogleGenerativeAI."""
        with patch.dict(os.environ, {"PROVIDER": "gemini"}, clear=False):
            os.environ.pop("MODEL", None)

            model = _build_model()

            from langchain_google_genai import ChatGoogleGenerativeAI
            assert isinstance(model, ChatGoogleGenerativeAI)
            assert model.model == "gemini-3.8-flash"

    def test_provider_groq_with_default_model(self):
        """PROVIDER=groq -> ChatGroq with default model."""
        with patch.dict(
            os.environ,
            {"PROVIDER": "groq", "GROQ_API_KEY": "test-key"},
            clear=False,
        ):
            os.environ.pop("MODEL", None)

            model = _build_model()

            from langchain_groq import ChatGroq
            assert isinstance(model, ChatGroq)
            # ChatGroq accepts model_name but stores it in model_name attribute
            # The config uses model as alias for model_name
            assert model.model_name == "openai/gpt-oss-120b"

    def test_model_override_with_gemini(self):
        """MODEL set with Gemini provider -> That model id is used."""
        with patch.dict(
            os.environ,
            {"PROVIDER": "gemini", "MODEL": "gemini-2.0-flash"},
            clear=False,
        ):
            model = _build_model()

            from langchain_google_genai import ChatGoogleGenerativeAI
            assert isinstance(model, ChatGoogleGenerativeAI)
            assert model.model == "gemini-2.0-flash"

    def test_model_override_with_groq(self):
        """MODEL set with Groq provider -> That model id is used."""
        with patch.dict(
            os.environ,
            {
                "PROVIDER": "groq",
                "MODEL": "llama2-70b-4096",
                "GROQ_API_KEY": "test-key",
            },
            clear=False,
        ):
            model = _build_model()

            from langchain_groq import ChatGroq
            assert isinstance(model, ChatGroq)
            assert model.model_name == "llama2-70b-4096"

    def test_unknown_provider_rejected(self):
        """PROVIDER=openai -> ValueError naming PROVIDER, value, and valid choices."""
        with patch.dict(os.environ, {"PROVIDER": "openai"}, clear=False):
            os.environ.pop("MODEL", None)

            with pytest.raises(ValueError) as exc:
                _build_model()

            message = str(exc.value)
            assert "PROVIDER" in message
            assert "openai" in message
            assert "gemini" in message
            assert "groq" in message

    def test_unknown_provider_case_insensitive(self):
        """Provider matching is case-insensitive."""
        with patch.dict(
            os.environ,
            {"PROVIDER": "GROQ", "GROQ_API_KEY": "test-key"},
            clear=False,
        ):
            os.environ.pop("MODEL", None)

            model = _build_model()

            from langchain_groq import ChatGroq
            assert isinstance(model, ChatGroq)


class TestPromptBuilder:
    """Test the prompt builder."""

    def test_prompt_reads_triage_policy(self):
        """Prompt builder reads and returns TRIAGE_POLICY.md content."""
        prompt = _build_prompt()

        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "Triage policy" in prompt or "Categories and routes" in prompt
        assert "billing" in prompt
        assert "P1" in prompt


class TestDecisionExtractor:
    """Test the decision extractor."""

    VALID_DECISION = {
        "category": "billing",
        "priority": "P2",
        "route": "billing-team",
        "rationale": "Double charge is money at stake.",
    }

    def test_extract_decision_from_dict(self):
        """Extract a valid decision from a dict in structured_response."""
        result = {"structured_response": self.VALID_DECISION}

        decision = _extract_decision(result)

        assert decision == self.VALID_DECISION
        assert isinstance(decision, dict)

    def test_extract_decision_from_triage_decision_object(self):
        """Extract a valid decision from a TriageDecision object."""
        from triage_schema import TriageDecision

        td = TriageDecision(**self.VALID_DECISION)
        result = {"structured_response": td}

        decision = _extract_decision(result)

        assert decision == self.VALID_DECISION
        assert isinstance(decision, dict)

    def test_extract_decision_validates_schema(self):
        """Extract validates the decision against TriageDecision schema."""
        invalid_decision = {
            "category": "billing",
            "priority": "P5",  # Invalid
            "route": "billing-team",
            "rationale": "Some reason",
        }
        result = {"structured_response": invalid_decision}

        with pytest.raises(ValidationError) as exc:
            _extract_decision(result)

        message = str(exc.value)
        assert "priority" in message

    def test_extract_decision_missing_structured_response(self):
        """Extract fails if structured_response is missing."""
        result = {}

        with pytest.raises(ValueError) as exc:
            _extract_decision(result)

        message = str(exc.value).lower()
        assert ("structured" in message) or ("output" in message)

    def test_extract_decision_missing_field(self):
        """Extract fails if a required field is missing."""
        incomplete_decision = {
            "category": "billing",
            "priority": "P2",
            # route is missing
            "rationale": "Some reason",
        }
        result = {"structured_response": incomplete_decision}

        with pytest.raises(ValidationError) as exc:
            _extract_decision(result)

        message = str(exc.value)
        assert "route" in message

    def test_extract_decision_with_extra_field(self):
        """Extract rejects decisions with extra fields."""
        extra_decision = {
            **self.VALID_DECISION,
            "confidence": 0.95,
        }
        result = {"structured_response": extra_decision}

        with pytest.raises(ValidationError) as exc:
            _extract_decision(result)

        message = str(exc.value)
        assert "confidence" in message

    def test_extract_decision_returns_dict_not_object(self):
        """Extract returns a plain dict, not a TriageDecision object."""
        from triage_schema import TriageDecision

        td = TriageDecision(**self.VALID_DECISION)
        result = {"structured_response": td}

        decision = _extract_decision(result)

        assert not isinstance(decision, TriageDecision)
        assert isinstance(decision, dict)


class TestTriageAsync:
    """Test the async triage function.

    These tests use a stub agent to avoid network calls and database access.
    """

    import asyncio

    VALID_DECISION = {
        "category": "billing",
        "priority": "P2",
        "route": "billing-team",
        "rationale": "Double charge is money at stake.",
    }

    def test_triage_success_on_first_attempt(self):
        """triage() succeeds when agent returns valid structured output on first attempt."""
        import asyncio
        from agent import triage

        async def run_test():
            mock_agent = AsyncMock()
            mock_agent.ainvoke = AsyncMock(
                return_value={"structured_response": self.VALID_DECISION}
            )

            mock_client = AsyncMock()
            mock_client.get_tools = AsyncMock(return_value=[])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("agent.create_agent", return_value=mock_agent):
                with patch("agent.MultiServerMCPClient", return_value=mock_client):
                    decision = await triage("T-1042")

            assert decision == self.VALID_DECISION
            assert isinstance(decision, dict)

        asyncio.run(run_test())

    def test_triage_retry_on_validation_failure(self):
        """triage() retries once if first attempt fails validation."""
        import asyncio
        from agent import triage

        async def run_test():
            mock_agent = AsyncMock()
            # First call returns invalid, second returns valid
            mock_agent.ainvoke = AsyncMock(
                side_effect=[
                    {"structured_response": {"category": "billing", "priority": "P5"}},  # Invalid
                    {"structured_response": self.VALID_DECISION},  # Valid
                ]
            )

            mock_client = AsyncMock()
            mock_client.get_tools = AsyncMock(return_value=[])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("agent.create_agent", return_value=mock_agent):
                with patch("agent.MultiServerMCPClient", return_value=mock_client):
                    decision = await triage("T-1042")

            assert decision == self.VALID_DECISION
            assert mock_agent.ainvoke.call_count == 2

        asyncio.run(run_test())

    def test_triage_fails_on_two_validation_failures(self):
        """triage() stops after second validation failure with a clear error."""
        import asyncio
        from agent import triage

        async def run_test():
            mock_agent = AsyncMock()
            # Both calls return invalid
            mock_agent.ainvoke = AsyncMock(
                side_effect=[
                    {"structured_response": {"category": "billing", "priority": "P5"}},
                    {"structured_response": {"category": "unknown"}},
                ]
            )

            mock_client = AsyncMock()
            mock_client.get_tools = AsyncMock(return_value=[])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("agent.create_agent", return_value=mock_agent):
                with patch("agent.MultiServerMCPClient", return_value=mock_client):
                    with pytest.raises(ValueError) as exc:
                        await triage("T-1042")

            message = str(exc.value)
            assert "validation" in message.lower()
            assert "twice" in message.lower()
            assert mock_agent.ainvoke.call_count == 2

        asyncio.run(run_test())

    def test_triage_fails_on_missing_structured_response(self):
        """triage() fails if agent returns no structured_response."""
        import asyncio
        from agent import triage

        async def run_test():
            mock_agent = AsyncMock()
            mock_agent.ainvoke = AsyncMock(return_value={})

            mock_client = AsyncMock()
            mock_client.get_tools = AsyncMock(return_value=[])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("agent.create_agent", return_value=mock_agent):
                with patch("agent.MultiServerMCPClient", return_value=mock_client):
                    with pytest.raises(ValueError) as exc:
                        await triage("T-1042")

            message = str(exc.value).lower()
            assert ("structured" in message) or ("output" in message)

        asyncio.run(run_test())

    def test_triage_is_async(self):
        """triage is an async coroutine function."""
        import asyncio
        from agent import triage

        assert asyncio.iscoroutinefunction(triage)

    def test_triage_calls_agent_with_correct_input(self):
        """triage() calls agent.ainvoke with the ticket_id."""
        import asyncio
        from agent import triage

        async def run_test():
            mock_agent = AsyncMock()
            mock_agent.ainvoke = AsyncMock(
                return_value={"structured_response": self.VALID_DECISION}
            )

            mock_client = AsyncMock()
            mock_client.get_tools = AsyncMock(return_value=[])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("agent.create_agent", return_value=mock_agent):
                with patch("agent.MultiServerMCPClient", return_value=mock_client):
                    await triage("T-9999")

            # Check that ainvoke was called with the ticket ID
            calls = mock_agent.ainvoke.call_args_list
            assert len(calls) >= 1
            first_call_input = calls[0][0][0]  # Get the input dict from first call
            assert "T-9999" in str(first_call_input)

        asyncio.run(run_test())

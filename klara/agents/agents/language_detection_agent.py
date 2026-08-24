"""
app/agents/language_detection_agent.py
──────────────────────────────────────
Detects German vs English from form text using spaCy and langdetect.

Scans incoming form submission and chat messages to determine the dominant
language. Returns {"language": "de" | "en", "confidence": 0.0-1.0}
"""
from __future__ import annotations

import structlog

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel

logger = structlog.get_logger(__name__)


class LanguageDetectionAgent(BaseAgent):
    name = "language_detection_agent"
    description = "Detects German vs English from form text using spaCy and langdetect"
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        input_data keys:
          text      (str, required)  — form message or chat text to analyze
        
        Returns:
          output: {"language": "de"|"en", "confidence": float}
        """
        text = input_data.get("text", "").strip()
        
        if not text:
            return AgentResult.fail("language_detection_agent requires non-empty 'text'.")
        
        try:
            from langdetect import detect, detect_langs
            
            # Detect language with confidence scores
            detected_lang = detect(text)
            all_langs = detect_langs(text)
            
            # Normalize to de/en, default to en if neither
            normalized_lang = "de" if detected_lang == "de" else "en"
            
            # Find confidence for normalized language
            confidence = 0.0
            for lang_prob in all_langs:
                lang_code = str(lang_prob).split(":")[0]
                if lang_code == normalized_lang:
                    confidence = float(str(lang_prob).split(":")[-1])
                    break
            
            logger.debug(
                "language_detection.detected",
                language=normalized_lang,
                confidence=round(confidence, 3),
                lead=context.lead_id,
            )
            
            return AgentResult.ok(output={
                "language": normalized_lang,
                "confidence": round(confidence, 3),
            })
        
        except ImportError:
            logger.error("language_detection.import_error", missing_lib="langdetect or spaCy")
            return AgentResult.fail("Language detection libraries not installed.")
        except Exception as e:
            logger.error("language_detection.error", error=str(e))
            return AgentResult.fail(f"Language detection failed: {str(e)}")

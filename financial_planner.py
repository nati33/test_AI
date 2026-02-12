#!/usr/bin/env python3
"""
Financial Planner Chat — Israel Market
=======================================
Interactive financial planning assistant that uses mislaka/GemelNet data
to answer questions about Israeli pension funds, provident funds (kupot gemel),
study funds (kranot hishtalmut), and retirement planning.

Supports multiple LLM backends:
  • OpenAI API (GPT-4 / GPT-3.5)
  • Anthropic API (Claude)
  • Local/custom endpoints (OpenAI-compatible)

Usage:
    python financial_planner.py                     # interactive chat
    python financial_planner.py --backend openai    # use OpenAI
    python financial_planner.py --backend anthropic  # use Anthropic
    python financial_planner.py --backend local --base-url http://localhost:8080/v1

Environment variables:
    OPENAI_API_KEY      — for OpenAI backend
    ANTHROPIC_API_KEY   — for Anthropic backend
"""

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

from financial_planner_prompt import SYSTEM_PROMPT, build_context_prompt


# ---------------------------------------------------------------------------
# Data loading utilities
# ---------------------------------------------------------------------------

def load_fund_data(data_dir: str) -> pd.DataFrame | None:
    """
    Attempt to load fund data from the downloaded GemelNet files.
    Returns a DataFrame with available fund information, or None.
    """
    data_path = Path(data_dir)
    if not data_path.exists():
        return None

    frames = []

    # Try loading CSV files from data_gov_il
    csv_dir = data_path / "data_gov_il"
    if csv_dir.exists():
        for f in csv_dir.glob("*.csv"):
            try:
                df = pd.read_csv(f, encoding="utf-8-sig")
                df["_source_file"] = f.name
                frames.append(df)
            except Exception:
                try:
                    df = pd.read_csv(f, encoding="cp1255")
                    df["_source_file"] = f.name
                    frames.append(df)
                except Exception:
                    continue

    # Try loading JSON datastore dumps
    for f in (csv_dir or data_path).glob("*_full_data.json") if csv_dir and csv_dir.exists() else []:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            records = raw.get("result", {}).get("records", [])
            if records:
                df = pd.DataFrame(records)
                df["_source_file"] = f.name
                frames.append(df)
        except Exception:
            continue

    if frames:
        return pd.concat(frames, ignore_index=True)
    return None


def format_data_summary(df: pd.DataFrame) -> str:
    """Create a concise summary of the loaded fund data for the LLM context."""
    lines = [f"Loaded {len(df)} records across {df['_source_file'].nunique()} data files."]
    lines.append(f"Columns: {', '.join(df.columns[:30])}")

    # Try to extract fund-level stats if common columns exist
    possible_fund_cols = ["FUND_NAME", "shem_kupa", "ShemKupa", "fund_name"]
    for col in possible_fund_cols:
        if col in df.columns:
            n_funds = df[col].nunique()
            lines.append(f"Unique funds ({col}): {n_funds}")
            break

    possible_company_cols = ["MANAGING_COMPANY", "hevra_menahelet", "ShemHevra"]
    for col in possible_company_cols:
        if col in df.columns:
            n_companies = df[col].nunique()
            lines.append(f"Unique managing companies: {n_companies}")
            break

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM Backend Abstraction
# ---------------------------------------------------------------------------

class ChatBackend:
    """Base class for LLM chat backends."""

    def send(self, messages: list[dict]) -> str:
        raise NotImplementedError


class OpenAIBackend(ChatBackend):
    """OpenAI-compatible API backend."""

    def __init__(self, model: str = "gpt-4", base_url: str | None = None):
        try:
            from openai import OpenAI
        except ImportError:
            print("Error: openai package not installed. Run: pip install openai")
            sys.exit(1)

        kwargs = {}
        if base_url:
            kwargs["base_url"] = base_url
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key and not base_url:
            print("Error: OPENAI_API_KEY environment variable not set.")
            sys.exit(1)
        if api_key:
            kwargs["api_key"] = api_key

        self.client = OpenAI(**kwargs)
        self.model = model

    def send(self, messages: list[dict]) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
            max_tokens=4096,
        )
        return response.choices[0].message.content


class AnthropicBackend(ChatBackend):
    """Anthropic Claude API backend."""

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        try:
            import anthropic
        except ImportError:
            print("Error: anthropic package not installed. Run: pip install anthropic")
            sys.exit(1)

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            print("Error: ANTHROPIC_API_KEY environment variable not set.")
            sys.exit(1)

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def send(self, messages: list[dict]) -> str:
        # Anthropic API uses system as a separate param
        system_msg = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                user_messages.append(m)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_msg,
            messages=user_messages,
        )
        return response.content[0].text


def get_backend(name: str, model: str | None = None, base_url: str | None = None) -> ChatBackend:
    """Factory for chat backends."""
    if name == "openai":
        return OpenAIBackend(model=model or "gpt-4", base_url=base_url)
    elif name == "anthropic":
        return AnthropicBackend(model=model or "claude-sonnet-4-20250514")
    elif name == "local":
        return OpenAIBackend(model=model or "local-model", base_url=base_url or "http://localhost:8080/v1")
    else:
        print(f"Unknown backend: {name}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Interactive Chat Loop
# ---------------------------------------------------------------------------

def run_chat(backend: ChatBackend, data_dir: str):
    """Run an interactive financial planner chat session."""
    # Build system prompt with data context
    system_prompt = build_context_prompt(data_dir)

    # Try to load and summarize fund data
    df = load_fund_data(data_dir)
    if df is not None:
        data_summary = format_data_summary(df)
        system_prompt += f"\n\n[LOADED DATA SUMMARY]\n{data_summary}"
        print(f"Loaded fund data: {len(df)} records from {data_dir}")
    else:
        print(f"No fund data found in {data_dir} — running in general-knowledge mode.")

    messages = [{"role": "system", "content": system_prompt}]

    print("=" * 60)
    print("  Financial Planner — Israel Market (Mislaka Data)")
    print("  Type 'quit' or 'exit' to end the session.")
    print("  Type 'data' to see available data summary.")
    print("=" * 60)
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession ended.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            print("Session ended.")
            break
        if user_input.lower() == "data":
            if df is not None:
                print(format_data_summary(df))
            else:
                print("No fund data loaded. Run gemelnet_downloader.py first.")
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            response = backend.send(messages)
            messages.append({"role": "assistant", "content": response})
            print(f"\nAdvisor: {response}\n")
        except Exception as e:
            print(f"\nError communicating with LLM: {e}\n")
            messages.pop()  # Remove failed user message


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Financial Planner Chat — Israel Market (Mislaka Data)"
    )
    parser.add_argument(
        "--backend",
        choices=["openai", "anthropic", "local"],
        default="openai",
        help="LLM backend to use (default: openai)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name (default: depends on backend)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Custom API base URL (for local/compatible endpoints)",
    )
    parser.add_argument(
        "--data-dir",
        default="./nati_Ai_test",
        help="Path to downloaded mislaka data (default: ./nati_Ai_test)",
    )
    args = parser.parse_args()

    backend = get_backend(args.backend, args.model, args.base_url)
    run_chat(backend, args.data_dir)


if __name__ == "__main__":
    main()

import json
import os
import urllib.request
from pathlib import Path
from datetime import datetime, timezone


SOFIA_ROOT = Path(__file__).resolve().parents[1]

INTAKE_FILE = SOFIA_ROOT / "sites" / "content_intake.json"
DRAFT_REGISTRY_FILE = SOFIA_ROOT / "sites" / "draft_registry.json"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("SOFIA_MODEL", "qwen2.5:14b")


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def find_intake_by_id(content_ideas, intake_id):
    for item in content_ideas:
        if item.get("intake_id") == intake_id:
            return item
    return None


def load_language_profile_for_draft(draft):
    workspace_path = draft.get("workspace_path", "")
    if not workspace_path:
        raise ValueError(f"Draft {draft.get('draft_id')} has no workspace_path")

    profile_path = SOFIA_ROOT / workspace_path / "language_profile.json"

    if not profile_path.exists():
        raise FileNotFoundError(f"Missing language profile: {profile_path}")

    return load_json(profile_path)


def build_prompt(draft, intake, language_profile):
    draft_input = intake.get("draft_input", {})
    seo = draft_input.get("seo", {})
    strategy = draft_input.get("strategy", {})
    quality = draft_input.get("quality_controls", {})

    content_rules = language_profile.get("content_rules", {})
    prompt_instructions = language_profile.get("prompt_instructions", {})
    cta_templates = language_profile.get("cta_templates", {})
    forbidden_elements = language_profile.get("forbidden_elements", [])
    preferred_terms = language_profile.get("preferred_terms", {})
    avoid_terms = language_profile.get("avoid_terms", [])
    faq_templates = language_profile.get("faq_templates", {})
    faq_intents = language_profile.get("faq_intents", [])

    language_name = content_rules.get("language_name", draft_input.get("language", draft.get("language", "")))
    regional_variant = content_rules.get("regional_variant", "")
    write_for_region = content_rules.get("write_for_region", "")
    tone = content_rules.get("tone", "professional, neutral, trustworthy")
    formality = content_rules.get("formality", "formal")

    return f"""
You are Sofia, an advanced SEO content writer specialized in professional polygraph services.

Your task is to generate HIGH-QUALITY, HUMAN-LIKE, SEO-OPTIMIZED content that is ready for publication.

--------------------------------------------------
LANGUAGE & STYLE
--------------------------------------------------
- Language: {language_name}
- Regional variant: {regional_variant}
- Target region: {write_for_region}
- Tone: {tone}
- Formality: {formality}

Write ONLY in the target language. Do not mix languages.

--------------------------------------------------
CONTENT GOAL
--------------------------------------------------
Topic: {draft_input.get("topic", draft.get("working_title", ""))}
Search intent: {draft.get("search_intent", "")}
Content type: {draft_input.get("content_type", "")}

Primary keyword: {seo.get("focus_keyphrase", draft.get("target_keyword", ""))}
Secondary keywords: {", ".join(draft_input.get("related_keywords", draft.get("secondary_keywords", [])))}

--------------------------------------------------
STRICT SEO RULES (MANDATORY)
--------------------------------------------------
- Minimum length: 800 words (preferably 1000–1200)
- Keyword density: 1–3% (natural usage ONLY)
- Use variations and LSI keywords naturally
- Include keyword in:
  * H1
  * first 100 words
  * at least one H2
- Avoid keyword stuffing

--------------------------------------------------
INTRO RULES (MANDATORY)
--------------------------------------------------
- Start with a direct, confident answer to the user's question
- Avoid generic phrases like "neste artigo"
- Use natural, human tone
- First paragraph must clearly answer the search intent
- Keep it short (2–4 sentences)

--------------------------------------------------
CONTENT STRUCTURE (MANDATORY)
--------------------------------------------------

Generate HTML content with the following structure:

<h1>Main title with keyword</h1>

<p>Short direct answer (2–3 sentences)</p>

<h2>Explanation of the concept</h2>
<p>Clear explanation with examples</p>

<h2>How it works / Practical examples</h2>
<p>Real-world applications (relationships, corporate, legal)</p>

<h2>Benefits and use cases</h2>
<ul>
<li>Use bullet points</li>
</ul>

<h2>Limitations and considerations</h2>
<p>Balanced and realistic explanation</p>

<h2>When to contact a professional</h2>
<p>Include soft CTA</p>

<h2>Frequently Asked Questions</h2>

REQUIREMENTS:
- Minimum 4 FAQ questions
- Use long-tail keywords
- Format:

<h3>Question</h3>
<p>Answer</p>

--------------------------------------------------
BODY DEPTH RULE:
--------------------------------------------------
For every main <h2> section before the FAQ:
- write 2 substantial paragraphs
- include practical context
- include one user-focused explanation
- avoid one-paragraph sections

--------------------------------------------------
WORD COUNT REQUIREMENT:
--------------------------------------------------
- The final article MUST contain at least 800 words before the FAQ is included.
- Target length: 1000–1200 words total.
- Do NOT write short summaries.
- Each main <h2> section before the FAQ must contain at least 2 paragraphs.
- Each paragraph must contain 3–5 sentences.
- The FAQ section must be additional content, not a replacement for body content.
- If the draft would be shorter than 800 words, expand each section with practical explanation, use cases, limitations, and professional context.

--------------------------------------------------
FAQ GENERATION (MANDATORY)
--------------------------------------------------
- Generate questions that look like real Google searches
- Use natural, conversational phrasing (not textbook language)
- Each question must be a realistic search query
- Include long-tail keywords
- Cover different user intents: cost, reliability, how it works, use cases, process, limitations
- Do NOT invent prices, durations, legal claims, or guarantees

FAQ INTENTS TO COVER:
{json.dumps(faq_intents, ensure_ascii=False, indent=2)}

FAQ EXAMPLE QUESTIONS (STYLE REFERENCE ONLY – DO NOT COPY EXACTLY):
{json.dumps(faq_templates.get("example_questions", []), ensure_ascii=False, indent=2)}

--------------------------------------------------
LANGUAGE QUALITY RULES
--------------------------------------------------
- Use natural, native-level language for the region
- Avoid literal translations
- Avoid uncommon or formal words that do not fit real usage
- Prefer simple and clear wording

--------------------------------------------------
EEAT RULES (MANDATORY)
--------------------------------------------------
- Show expertise (professional tone)
- Avoid exaggerated claims (NO: 100%, guaranteed, certified)
- Keep realistic language
- Build trust (clear explanations, balanced tone)

--------------------------------------------------
LINKING RULES
--------------------------------------------------
- Do NOT insert links manually
- Write natural anchor text opportunities for internal linking

--------------------------------------------------
CTA RULES
--------------------------------------------------
Use soft CTA (not aggressive sales):
"contact a professional examiner for a confidential evaluation"

--------------------------------------------------
FORBIDDEN
--------------------------------------------------
{json.dumps(forbidden_elements, ensure_ascii=False)}

--------------------------------------------------
OUTPUT FORMAT
--------------------------------------------------
- Output ONLY clean HTML
- No markdown
- No ```html
- No explanations
"""

def generate_section(prompt_base: str, section_title: str):
    section_prompt = f"""
{prompt_base}

Write ONLY the following section:

<section>
<h2>{section_title}</h2>

RULES:
- Minimum 150–200 words
- At least 2 paragraphs
- Each paragraph 3–5 sentences
- Use natural language
- Be specific and practical
- Do NOT write the full article
</section>
"""

    return call_ollama(section_prompt)

def call_ollama(prompt):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False
    }

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(request, timeout=600) as response:
        result = json.loads(response.read().decode("utf-8"))

    return result.get("response", "").strip()

def generate_section(prompt_base: str, section_title: str):
    section_prompt = f"""
{prompt_base}

Write ONLY this section:

<h2>{section_title}</h2>

SECTION RULES:
- Minimum 150–200 words
- At least 2 paragraphs
- Each paragraph must have 3–5 sentences
- Use natural, professional language
- Be specific and practical
- Do NOT write the full article
- Do NOT include FAQ
- Do NOT include markdown fences
""".strip()

    return call_ollama(section_prompt)

def main():
    print("=== Sofia: Generate AI Draft Content ===\n")

    intake_data = load_json(INTAKE_FILE)
    draft_data = load_json(DRAFT_REGISTRY_FILE)

    content_ideas = intake_data.get("content_ideas", [])
    drafts = draft_data.get("drafts", [])

    generated = 0

    for draft in drafts:
        if draft.get("draft_status") != "approved":
            continue

        intake_id = draft.get("created_from_intake_id", "")
        intake = find_intake_by_id(content_ideas, intake_id)

        if not intake:
            print(f"Skipped {draft.get('draft_id')}: intake not found")
            continue

        if not intake.get("draft_input"):
            print(f"Skipped {draft.get('draft_id')}: missing draft_input")
            continue

        try:
            language_profile = load_language_profile_for_draft(draft)
        except Exception as e:
            print(f"Skipped {draft.get('draft_id')}: {e}")
            continue

        print(f"Generating content for {draft.get('draft_id')}: {draft.get('working_title')}")

        prompt = build_prompt(draft, intake, language_profile)

        draft_input = intake.get("draft_input", {})
        seo = draft_input.get("seo", {})
        strategy = draft_input.get("strategy", {})
        faq_templates = language_profile.get("faq_templates", {})

        page_title = seo.get("page_title") or draft.get("working_title", "")
        topic = draft_input.get("topic", draft.get("working_title", ""))

        required_sections = strategy.get("required_sections", [])

        if not required_sections:
            required_sections = [
                "Explicação do conceito",
                "Como funciona / Exemplos práticos",
                "Vantagens e casos de uso",
                "Limitações e considerações",
                "Quando contactar um examinador profissional"
            ]

        try:
            intro_prompt = f"""
{prompt}

Write ONLY the beginning of the article.

OUTPUT STRUCTURE:
<h1>{page_title}</h1>
<p>Introductory answer paragraph</p>

INTRO RULES:
- 100–150 words
- Directly answer the user search intent
- Include the primary keyword naturally
- Do not include any <h2>
- Do not include FAQ
- Do not include markdown fences
""".strip()

            intro = call_ollama(intro_prompt)

            body_parts = []

            for section_title in required_sections:
                print(f"  Generating section: {section_title}")
                section_content = generate_section(prompt, section_title)
                body_parts.append(section_content)

            faq_heading = faq_templates.get("section_heading", "FAQ")
            min_questions = faq_templates.get("minimum_questions", 4)
            max_questions = faq_templates.get("maximum_questions", 6)

            faq_prompt = f"""
{prompt}

Write ONLY the FAQ section.

OUTPUT STRUCTURE:
<h2>{faq_heading}</h2>
<h3>Question 1</h3>
<p>Answer 1</p>

FAQ RULES:
- Include between {min_questions} and {max_questions} questions
- Each question must use <h3>
- Each answer must use one <p>
- Questions must sound like real Google searches
- Use long-tail keyword style questions
- Do not invent prices, durations, phone numbers, addresses, legal claims, or guarantees
- Do not include markdown fences
""".strip()

            faq = call_ollama(faq_prompt)

            content = intro + "\n\n" + "\n\n".join(body_parts) + "\n\n" + faq

        except Exception as e:
            print(f"ERROR generating content for {draft.get('draft_id')}: {e}")
            continue

        draft["generated_content"] = {
            "generated_at": now_utc(),
            "model": OLLAMA_MODEL,
            "format": "html",
            "language_profile_version": language_profile.get("version", ""),
            "generation_mode": "section_based",
            "content": content
        }

        draft["draft_status"] = "content_generated"
        generated += 1

        print(f"Content generated for {draft.get('draft_id')}\n")

    save_json(DRAFT_REGISTRY_FILE, draft_data)

    print(f"AI drafts generated: {generated}")


if __name__ == "__main__":
    main()
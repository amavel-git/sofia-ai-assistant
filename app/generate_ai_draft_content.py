import json
import sys
from pathlib import Path
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_workspace(workspaces, workspace_id):
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def get_drafts(draft_registry):
    if isinstance(draft_registry, dict) and "drafts" in draft_registry:
        return draft_registry["drafts"]
    if isinstance(draft_registry, list):
        return draft_registry
    return []


def find_draft(draft_registry, draft_id):
    for draft in get_drafts(draft_registry):
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def slugify(text):
    return (
        text.lower()
        .replace(" ", "-")
        .replace("á", "a")
        .replace("à", "a")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )


def generate_html(draft, workspace):
    title = draft.get("title", "")
    keyphrase = draft.get("focus_keyphrase", "")
    country = workspace.get("country", "")

    return f"""
<h1>{title}</h1>

<p>O {keyphrase} é um serviço profissional destinado a apoiar particulares, empresas e organizações que necessitam de uma avaliação estruturada de veracidade em situações sensíveis.</p>

<h2>Serviço profissional de polígrafo em {country}</h2>

<p>Uma avaliação poligráfica deve ser conduzida por um examinador qualificado, com metodologia adequada, entrevista pré-teste, formulação técnica das perguntas e análise criteriosa dos dados fisiológicos registados durante o exame.</p>

<h2>Quando pode ser útil um teste de polígrafo?</h2>

<p>O polígrafo pode ser utilizado em contextos privados, empresariais ou investigativos, sempre que exista uma necessidade legítima de clarificar declarações ou comportamentos específicos. Cada caso deve ser analisado individualmente para determinar se o exame é adequado.</p>

<h2>Validação profissional e confidencialidade</h2>

<p>Todos os exames devem respeitar princípios de confidencialidade, consentimento informado e limites técnicos da poligrafia. O objetivo não é testar perguntas isoladas, mas avaliar a veracidade do testemunho em relação ao tema investigado.</p>

<h2>Disponibilidade local</h2>

<p>O atendimento pode ser organizado conforme a disponibilidade do examinador local. Em alguns casos, o examinador poderá deslocar-se para outras cidades ou regiões, dependendo das condições logísticas e da natureza do caso.</p>

<h2>Contacte-nos</h2>

<p>Para saber se o seu caso é adequado para uma avaliação poligráfica, entre em contacto e descreva brevemente a situação. A informação será analisada com discrição e profissionalismo.</p>
""".strip()


def main():
    if len(sys.argv) < 3:
        print("Usage: python app/generate_ai_draft_content.py WORKSPACE_ID DRAFT_ID")
        return

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)

    if not workspace:
        print(f"Workspace not found: {workspace_id}")
        sys.exit(1)

    draft_registry_path = ROOT / workspace["draft_registry_path"]
    draft_registry = load_json(draft_registry_path)

    draft = find_draft(draft_registry, draft_id)

    if not draft:
        print(f"Draft not found: {draft_id}")
        sys.exit(1)

    title = draft.get("title", "")
    keyphrase = draft.get("focus_keyphrase", "")

    draft["slug"] = draft.get("slug") or slugify(title)
    draft["meta_description"] = draft.get("meta_description") or f"Informação profissional sobre {keyphrase}, com atendimento confidencial e análise técnica adequada."
    draft["html_content"] = generate_html(draft, workspace)
    draft["html_generated_at"] = now_iso()
    draft["updated_at"] = now_iso()

    save_json(draft_registry_path, draft_registry)

    print("AI draft content generated successfully.")
    print(f"Workspace: {workspace_id}")
    print(f"Draft: {draft_id}")
    print(f"Slug: {draft['slug']}")


if __name__ == "__main__":
    main()
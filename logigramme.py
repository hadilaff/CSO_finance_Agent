"""Génération automatique de logigrammes à partir d'expressions de besoin (EB).

Flow: EB PDF → extraction texte → analyse LLM → structure JSON → graphe Graphviz → image
"""
from __future__ import annotations

import io
import json
import re
import uuid
from pathlib import Path

from config import CHAT_MODEL, get_groq_client
from rag import parse_file

# Stocker les logigrammes générés en mémoire (comme les decks)
_LOGIGRAMMES: dict[str, dict] = {}


LOGIGRAMME_SYSTEM_PROMPT = """Tu es un expert en analyse de processus et génération de logigrammes.

Ta mission : analyser une "Expression de Besoin" (EB) décrivant un processus métier et produire une structure JSON représentant un logigramme.

Règles d'extraction:
- Identifie TOUTES les étapes du processus dans l'ordre chronologique
- Repère les points de décision (conditions, validations, choix)
- Identifie les acteurs/rôles impliqués à chaque étape
- Capture les conditions de passage d'une étape à l'autre
- Note les documents produits/utilisés
- Identifie les boucles ou retours en arrière

Structure de sortie (JSON uniquement, pas de prose):
{
  "titre": "Titre du processus",
  "acteurs": ["Acteur1", "Acteur2", ...],
  "etapes": [
    {
      "id": "etape_1",
      "type": "action",  // "action", "decision", "debut", "fin"
      "label": "Description courte de l'étape",
      "acteur": "Acteur responsable",
      "suivant": "etape_2"  // ou ["etape_2", "etape_3"] si décision
    },
    {
      "id": "etape_2",
      "type": "decision",
      "label": "Condition à vérifier ?",
      "acteur": "Acteur",
      "branches": [
        {"condition": "Oui", "suivant": "etape_3"},
        {"condition": "Non", "suivant": "etape_4"}
      ]
    }
  ]
}

IMPORTANT: Retourne UNIQUEMENT le JSON, sans code fences, sans texte avant/après."""


def _extract_process_structure(eb_text: str) -> dict:
    """Utilise LLM pour extraire la structure du processus depuis l'EB."""
    client = get_groq_client()
    
    # Limiter le texte si trop long (garder les sections clés)
    if len(eb_text) > 8000:
        # Garder début + sections process si identifiables
        eb_text = eb_text[:8000] + "\n\n[...texte tronqué...]"
    
    prompt = f"""Expression de Besoin à analyser:

{eb_text}

Extrait la structure complète du processus sous forme JSON."""
    
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": LOGIGRAMME_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        
        raw = (resp.choices[0].message.content or "").strip()
        # Nettoyer code fences si présents
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.M).strip()
        structure = json.loads(raw)
        return structure
        
    except json.JSONDecodeError as e:
        raise ValueError(f"Échec du parsing JSON de la structure: {e}\nRéponse brute: {raw[:500]}")
    except Exception as e:
        raise RuntimeError(f"Échec de l'extraction de structure: {e}")


def _generate_graphviz(structure: dict) -> str:
    """Génère le code Graphviz DOT à partir de la structure JSON.
    
    Style logigramme BPMN standard :
    - Début : cercle blanc vide (○) → rectangle message
    - Fin   : rectangle message → cercle noir plein (●)
    - Action: rectangle
    - Décision: losange
    """
    titre = structure.get("titre", "Processus")
    etapes = structure.get("etapes", [])

    dot_lines = [
        "digraph Processus {",
        "    rankdir=TB;",
        "    node [fontname=\"Arial\", fontsize=11];",
        "    edge [fontname=\"Arial\", fontsize=10];",
        f'    label="{titre}";',
        "    labelloc=t;",
        "    fontsize=14;",
        "    fontname=\"Arial\";",
        "",
    ]

    for etape in etapes:
        eid = etape["id"]
        label = etape["label"].replace('"', '\\"')
        etype = etape.get("type", "action")
        acteur = etape.get("acteur", "")

        full_label = f"{label}\\n({acteur})" if acteur else label

        if etype == "debut":
            # Cercle blanc vide + rectangle message
            dot_lines.append(f'    {eid}_circle [label="", shape=circle, style="", width=0.3, height=0.3];')
            dot_lines.append(f'    {eid} [label="{full_label}", shape=box, style=""];')
            dot_lines.append(f'    {eid}_circle -> {eid} [arrowhead=none];')
        
        elif etype == "fin":
            # Rectangle message + cercle noir plein
            dot_lines.append(f'    {eid} [label="{full_label}", shape=box, style=""];')
            dot_lines.append(f'    {eid}_circle [label="", shape=circle, style=filled, fillcolor=black, width=0.3, height=0.3];')
            dot_lines.append(f'    {eid} -> {eid}_circle [arrowhead=none];')
        
        elif etype == "decision":
            # Losange
            dot_lines.append(f'    {eid} [label="{full_label}", shape=diamond, style=""];')
        
        else:  # action
            # Rectangle simple
            dot_lines.append(f'    {eid} [label="{full_label}", shape=box, style=""];')

    dot_lines.append("")

    # Arêtes entre étapes (skip debut/fin circles, ils sont gérés au-dessus)
    for etape in etapes:
        eid = etape["id"]
        etype = etape.get("type", "action")

        # Pour debut, la flèche part du rectangle (pas du cercle)
        # Pour fin, la flèche arrive au rectangle (pas au cercle)
        
        if "branches" in etape:
            for branche in etape["branches"]:
                condition = branche.get("condition", "").replace('"', '\\"')
                suivant = branche.get("suivant")
                if suivant:
                    # Si suivant est "fin", pointer vers le rectangle, pas le cercle
                    target = suivant
                    dot_lines.append(f'    {eid} -> {target} [label="{condition}"];')

        elif "suivant" in etape:
            suivant = etape["suivant"]
            if isinstance(suivant, list):
                for s in suivant:
                    dot_lines.append(f'    {eid} -> {s};')
            elif suivant:
                # Si c'est debut qui pointe, partir du rectangle
                source = eid
                dot_lines.append(f'    {source} -> {suivant};')

    dot_lines.append("}")
    return "\n".join(dot_lines)


def _render_graphviz(dot_code: str, format: str = "png") -> bytes:
    """Rend le code DOT en image avec Graphviz."""
    try:
        import graphviz
    except ImportError:
        raise RuntimeError(
            "graphviz package not installed. Run: pip install graphviz\n"
            "Also install Graphviz system binary: https://graphviz.org/download/"
        )
    
    try:
        graph = graphviz.Source(dot_code)
        # Render to bytes
        return graph.pipe(format=format)
    except Exception as e:
        raise RuntimeError(f"Graphviz rendering failed: {e}")


def generate_logigramme_from_eb(filename: str, data: bytes) -> dict:
    """Pipeline complet: EB PDF → structure → logigramme PNG.
    
    Returns:
        dict avec logigramme_id, filename, size_bytes, structure (JSON)
    """
    # 1. Extraire le texte de l'EB
    try:
        eb_text = parse_file(filename, data)
    except Exception as e:
        raise ValueError(f"Échec du parsing du PDF '{filename}': {e}")
    
    if not eb_text.strip():
        raise ValueError(f"Aucun texte extrait du fichier '{filename}' (PDF scanné ?)")
    
    # 2. Analyser avec Azure OpenAI
    structure = _extract_process_structure(eb_text)
    
    # 3. Générer le DOT
    dot_code = _generate_graphviz(structure)
    
    # 4. Render avec Graphviz
    png_bytes = _render_graphviz(dot_code, format="png")
    
    # 5. Stocker en mémoire
    logi_id = uuid.uuid4().hex[:12]
    output_filename = Path(filename).stem + "_logigramme.png"
    
    _LOGIGRAMMES[logi_id] = {
        "bytes": png_bytes,
        "filename": output_filename,
        "structure": structure,
        "dot_code": dot_code,
        "source_file": filename,
    }
    
    return {
        "logigramme_id": logi_id,
        "filename": output_filename,
        "size_bytes": len(png_bytes),
        "structure": structure,
        "note": "Logigramme généré. L'UI affichera un bouton de téléchargement.",
    }


def get_logigramme(logi_id: str) -> dict | None:
    """Récupère un logigramme stocké en mémoire."""
    return _LOGIGRAMMES.get(logi_id)

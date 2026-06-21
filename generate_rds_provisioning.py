#!/usr/bin/env python3
"""Génère rds_provisioning.py directement dans son état final des sections 1 à 5
(ou moins, via --steps), en exécutant les commandes `cat` du README.md dans l'ordre.

Évite de rejouer les commandes une par une à chaque test du support — utile pour
l'animateur ou pour quiconque veut valider rapidement le script complet plutôt que
de suivre le déroulé pédagogique pas à pas (qui reste le chemin recommandé pour les
participants en lab).

Variables d'environnement requises (les mêmes que celles du README, section 1) :
  VPC_ID, PRIVATE_SUBNET_1, PRIVATE_SUBNET_2, USER_ID, ALLOWED_CIDR
  PUBLIC_SUBNET_1, PUBLIC_SUBNET_2 (uniquement si ALLOWED_CIDR est une IP publique)

Elles doivent être EXPORTÉES (pas seulement définies) pour être visibles par ce
script, qui s'exécute dans un sous-processus. Le plus simple : copiez .env.example
en .env, éditez vos valeurs, puis "source .env" avant de lancer ce script.

Exemple :
  cp .env.example .env   # une seule fois, puis éditez .env
  source .env             # à refaire dans chaque nouveau terminal
  python3 generate_rds_provisioning.py
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

README_PATH = Path(__file__).parent / "README.md"
HEREDOC_RE = re.compile(r"```bash\n((?:cat (?:>|>>) rds_provisioning\.py << '?EOF'?\n).*?\nEOF\n)```", re.S)
SECTION_RE = re.compile(r"^## (\d+) — .*$", re.M)


def extract_blocks(steps: int) -> list[str]:
    text = README_PATH.read_text()
    headings = list(SECTION_RE.finditer(text))
    starts = {int(m.group(1)): m.start() for m in headings}

    if 1 not in starts:
        sys.exit("Impossible de trouver la section 1 dans README.md.")

    start = starts[1]
    end = starts.get(steps + 1, len(text))
    section_text = text[start:end]

    blocks = HEREDOC_RE.findall(section_text)
    if not blocks:
        sys.exit("Aucun bloc 'cat > rds_provisioning.py' trouvé pour ces sections.")
    return blocks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--steps", type=int, default=5, choices=range(1, 6), help="générer jusqu'à cette section incluse (1-5, défaut 5)")
    parser.add_argument("--output-dir", default=".", help="répertoire où écrire rds_provisioning.py (défaut: répertoire courant)")
    args = parser.parse_args()

    required = ["VPC_ID", "PRIVATE_SUBNET_1", "PRIVATE_SUBNET_2", "USER_ID", "ALLOWED_CIDR"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        sys.exit(f"Variables d'environnement manquantes : {', '.join(missing)}. Voir l'en-tête de ce script.")

    blocks = extract_blocks(args.steps)
    print(f"{len(blocks)} commande(s) extraite(s) du README (sections 1 à {args.steps}).")

    for block in blocks:
        result = subprocess.run(["bash", "-c", block], cwd=args.output_dir)
        if result.returncode != 0:
            sys.exit("Échec lors de l'exécution d'une commande de génération — voir l'erreur ci-dessus.")

    output_path = Path(args.output_dir) / "rds_provisioning.py"
    print(f"Généré : {output_path.resolve()}")


if __name__ == "__main__":
    main()

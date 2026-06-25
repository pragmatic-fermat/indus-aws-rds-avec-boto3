# Lab — Industrialiser la création de bases RDS avec boto3

**Durée : 1h10** · **Niveau : confirmé (Python + AWS)**

## Contexte

Plusieurs bases de données on-premise doivent être migrées vers Amazon RDS :

- des bases **MySQL** → **Amazon RDS MariaDB**
- des bases **PostgreSQL** → **Amazon RDS PostgreSQL**

Plutôt que de créer chaque instance à la main dans la console, l'objectif de ce lab est de développer un **script Python (boto3) industrialisable**, qui standardise la création des instances RDS : réseau, paramètres, sécurité, tags, et cycle de vie (création / vérification / modification / suppression).

À la fin du lab, vous aurez un script réutilisable comme template pour toutes les futures migrations vers RDS.

## Objectifs pédagogiques

À l'issue du lab, vous serez capable de :

- créer une instance RDS (MariaDB ou PostgreSQL) via `create_db_instance` ;
- créer et associer un groupe de sous-réseaux via `create_db_subnet_group` ;
- créer et configurer un groupe de paramètres standardisé via `create_db_parameter_group` / `modify_db_parameter_group` ;
- appliquer une gouvernance de tags via le paramètre `Tags` à la création de chaque ressource ;
- configurer des Security Groups EC2 homogènes (ports, CIDR, chiffrement, sous-réseau privé) ;
- vérifier l'état des ressources via les API `describe_*` ;
- modifier et supprimer une instance de façon contrôlée ;
- généraliser le script en template réutilisable, piloté par configuration.

## Pré-requis

- Une machine personnelle (Linux ou Windows) avec Python ≥ 3.9 fonctionnel, et un accès réseau **direct** à l'API AWS (pas de proxy ni de filtrage sortant bloquant les endpoints AWS).
- Les paquets nécessaires :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install boto3
```

- Une clé d'accès AWS (Access Key ID + Secret Access Key) transmise en début de session via un lien secret éphémère — voir [Configuration des clés d'accès](#configuration-des-clés-daccès-boto3-uniquement).
- Un accès à un compte AWS sandbox **commun à tous les participants**, avec :
  - un **VPC unique, partagé** par l'ensemble du groupe (mêmes `VPC_ID` et sous-réseaux pour tout le monde, en **eu-west-1**), avec au moins 2 sous-réseaux **privés** dans des AZ différentes, et, si vous comptez tester l'option « IP publique » d'`ALLOWED_CIDR` (section 1), au moins 2 sous-réseaux **publics** (avec route vers une Internet Gateway) dans des AZ différentes — l'identifiant réel du VPC et des sous-réseaux vous sera communiqué via le même lien secret éphémère que les clés d'accès, à reporter dans les constantes `VPC_ID` / `PRIVATE_SUBNET_IDS` / `PUBLIC_SUBNET_IDS` du script (ce ne sont pas des secrets à proprement parler, mais des identifiants d'infrastructure propres à la session, qui n'ont pas vocation à être publiés dans ce support) ;
  - des droits IAM sur `rds:*`, `ec2:*SecurityGroup*`, `ec2:Describe*` ;
- Votre **numéro de participant** (1, 2, 3...), communiqué par l'animateur en même temps que les clés d'accès — `0` est réservé à l'animateur.

> **VPC partagé** : comme tout le groupe travaille dans le même VPC, chaque participant doit suffixer ses ressources par son numéro (`-userX`) pour éviter toute collision de nom avec les autres. C'est géré automatiquement par le script via la constante `USER_ID` (section 1) — vérifiez juste que vous avez bien renseigné votre numéro avant de créer quoi que ce soit.

> **Coût et durée** : la création d'une instance RDS prend réellement 5 à 10 minutes. Pensez à lancer la création tôt dans une section et à enchaîner sur la suite pendant le provisioning. **Toutes les ressources créées pendant la session sont détruites à la fin** (section [Nettoyage](#nettoyage-fin-de-lab)) — ne laissez rien tourner après le lab.

## Configuration des clés d'accès

Vos clés d'accès vous seront communiquées en début de session via un lien secret éphémère. Renseignez-les dans `.env` (les deux premières lignes) :

```bash
export AWS_ACCESS_KEY_ID="<votre access key id>"
export AWS_SECRET_ACCESS_KEY="<votre secret access key>"
```

Puis chargez le fichier dans votre terminal (à refaire dans chaque nouveau terminal) :

```bash
source .env
```

boto3 lit ces variables d'environnement automatiquement. Vérifiez que les credentials sont valides avant de continuer :

```bash
python3 -c "import boto3; print(boto3.client('sts', region_name='eu-west-1').get_caller_identity()['Account'])"
```

**Résultat attendu** : l'identifiant du compte AWS sandbox (12 chiffres), sans erreur. Si vous obtenez `NoCredentialsError` ou `InvalidClientTokenId`, vérifiez que `.env` a bien été édité avec vos vraies valeurs et que `source .env` a été exécuté dans ce terminal.

## Architecture du script

Le script est piloté par une **configuration par moteur**, afin de traiter MariaDB et PostgreSQL avec le même code, sans duplication :

```python
ENGINE_CONFIG = {
    "mariadb": {
        "engine": "mariadb",
        "engine_version": "10.11.6",
        "port": 3306,
        "parameter_group_family": "mariadb10.11",
        "source_db": "mysql",
    },
    "postgres": {
        "engine": "postgres",
        "engine_version": "16.3",
        "port": 5432,
        "parameter_group_family": "postgres16",
        "source_db": "postgresql",
    },
}
```

Chaque fonction du script prend `engine` (`"mariadb"` ou `"postgres"`) en paramètre et va chercher la configuration correspondante. On exécutera donc le script deux fois (une fois par moteur) avec les mêmes fonctions.

*(Aperçu pédagogique uniquement — rien à taper ici, le code réel à créer est donné en section 1.)*

Le fichier `rds_provisioning.py` sera créé puis complété au fil des sections, à chaque fois via une commande `cat` plutôt qu'en copiant manuellement le code dans un éditeur.

---

## Plan du lab

| # | Section | Durée indicative |
|---|---|---|
| 1 | [Mise en place & standard de configuration](#1--mise-en-place--standard-de-configuration) | 7 min |
| 2 | [Security Groups](#2--security-groups) | 7 min |
| 3 | [DB Subnet Group](#3--db-subnet-group) | 5 min |
| 4 | [DB Parameter Group](#4--db-parameter-group) | 7 min |
| 5 | [Création de l'instance RDS](#5--création-de-linstance-rds) | 10 min |
| 6 | [Vérification des ressources](#6--vérification-des-ressources) | 5 min |
| 7 | [Test de connexion SQL](#7--test-de-connexion-sql) | 5 min |
| 8 | [Modification contrôlée](#8--modification-contrôlée) | 5 min |
| 9 | [Suppression contrôlée](#9--suppression-contrôlée) | 5 min |
| 10 | [Généralisation en template réutilisable](#10--généralisation-en-template-réutilisable) | 7 min |
| — | [Nettoyage final](#nettoyage-fin-de-lab) | 5 min |

---

## 1 — Mise en place & standard de configuration

On démarre le script par les imports, le client boto3, et le **standard commun** (naming, tags, configuration par moteur) qui sera réutilisé dans toutes les fonctions suivantes. Le VPC étant partagé par tout le groupe, on introduit ici `USER_ID` : **chacun remplace cette valeur par son propre numéro de participant** avant de continuer — c'est ce qui garantit que vos ressources n'entrent jamais en collision avec celles des autres.

Renseignez d'abord vos identifiants réseau (reçus via le lien secret éphémère) et votre numéro de participant dans un fichier `.env`, à partir du modèle fourni dans le dépôt — `.env` n'est **jamais commité** (voir `.gitignore`), c'est volontaire puisqu'il contient les vraies valeurs du sandbox :

```bash
cp .env.example .env
```

Éditez `.env` en renseignant les variables ci-dessous, puis chargez ces valeurs dans votre terminal :

| Variable | Signification |
|---|---|
| `AWS_ACCESS_KEY_ID` | Clé d'accès AWS communiquée en début de session |
| `AWS_SECRET_ACCESS_KEY` | Clé secrète associée |
| `VPC_ID` | Identifiant du VPC partagé par le groupe (`vpc-...`) |
| `PRIVATE_SUBNET_1` | Sous-réseau privé en eu-west-1a (`subnet-...`) |
| `PRIVATE_SUBNET_2` | Sous-réseau privé en eu-west-1b (`subnet-...`) |
| `PUBLIC_SUBNET_1` | Sous-réseau public en eu-west-1a — requis uniquement si `ALLOWED_CIDR` est une IP publique |
| `PUBLIC_SUBNET_2` | Sous-réseau public en eu-west-1b — requis uniquement si `ALLOWED_CIDR` est une IP publique |
| `ALLOWED_CIDR` | Réseau autorisé à se connecter aux bases : CIDR du VPC (base privée), votre IP publique via `$(curl -4 -s ip.me)` (base publique), ou un CIDR libre |
| `USER_ID` | Votre numéro de participant (1, 2, 3…) — `0` est réservé à l'animateur |
| `MASTER_PASSWORD` | Mot de passe administrateur des instances RDS (lab uniquement) |

```bash
source .env
```

> **Pourquoi `source` et pas juste éditer le fichier ?** Les commandes qui suivent (le `cat` ci-dessous, et `generate_rds_provisioning.py`) ont besoin de ces valeurs comme **variables d'environnement**. `source .env` exécute le fichier dans votre shell actuel et — grâce au mot-clé `export` qu'il contient — rend ces variables visibles par les commandes et scripts que vous lancez ensuite, dans ce même terminal.

Puis générez le fichier — les variables shell chargées par `.env` sont interpolées directement dans le code écrit (notez le `EOF` non quoté, qui autorise cette substitution) :

```bash
cat > rds_provisioning.py << EOF
import argparse
import ipaddress
import time

import boto3
import botocore

REGION = "eu-west-1"  # adaptez à la région de votre sandbox
VPC_ID = "$VPC_ID"  # VPC unique, partagé par tout le groupe
PRIVATE_SUBNET_IDS = ["$PRIVATE_SUBNET_1", "$PRIVATE_SUBNET_2"]  # 2 AZ minimum
PUBLIC_SUBNET_IDS = ["$PUBLIC_SUBNET_1", "$PUBLIC_SUBNET_2"]  # 2 AZ minimum, avec route vers une Internet Gateway
ALLOWED_CIDR = "$ALLOWED_CIDR"  # réseau autorisé à se connecter aux bases
ALLOWED_CIDR = str(ipaddress.ip_network(ALLOWED_CIDR, strict=False))  # normalise IP nue (ex. 1.2.3.4) en notation CIDR (1.2.3.4/32) — requis par l'API EC2
USER_ID = "$USER_ID"  # VOTRE numéro de participant (1, 2, 3...) ; 0 = animateur
MASTER_PASSWORD = "$MASTER_PASSWORD"  # mot de passe administrateur des instances RDS (lab uniquement)

# Si ALLOWED_CIDR est une plage privée (RFC1918, ex. le CIDR du VPC), la base reste privée.
# Si c'est une IP/plage routable sur Internet (ex. votre IP publique), la base est rendue publique
# ET déployée dans les sous-réseaux publics, pour être réellement joignable.
PUBLICLY_ACCESSIBLE = not ipaddress.ip_network(ALLOWED_CIDR, strict=False).is_private
SUBNET_IDS = PUBLIC_SUBNET_IDS if PUBLICLY_ACCESSIBLE else PRIVATE_SUBNET_IDS


def _require_non_empty(name: str, value: str) -> None:
    if not value or not value.strip():
        raise SystemExit(f"Configuration invalide : '{name}' est vide ou non défini (avez-vous bien fait 'source .env' avant le 'cat' ?).")


_require_non_empty("VPC_ID", VPC_ID)
_require_non_empty("USER_ID", USER_ID)
_require_non_empty("ALLOWED_CIDR", ALLOWED_CIDR)
_require_non_empty("MASTER_PASSWORD", MASTER_PASSWORD)
for _i, _subnet in enumerate(PRIVATE_SUBNET_IDS, start=1):
    _require_non_empty(f"PRIVATE_SUBNET_{_i}", _subnet)
if PUBLICLY_ACCESSIBLE:
    for _i, _subnet in enumerate(PUBLIC_SUBNET_IDS, start=1):
        _require_non_empty(f"PUBLIC_SUBNET_{_i}", _subnet)

rds = boto3.client("rds", region_name=REGION)
ec2 = boto3.client("ec2", region_name=REGION)


def _default_engine_version(engine: str) -> dict:
    """Version par défaut et famille de paramètres associée, récupérées dynamiquement
    plutôt que codées en dur : AWS déprécie régulièrement les anciennes versions RDS,
    une version figée finit toujours par devenir invalide."""
    version = rds.describe_db_engine_versions(Engine=engine, DefaultOnly=True)["DBEngineVersions"][0]
    return {
        "engine_version": version["EngineVersion"],
        "parameter_group_family": version["DBParameterGroupFamily"],
    }


ENGINE_CONFIG = {
    "mariadb": {"engine": "mariadb", "port": 3306, **_default_engine_version("mariadb")},
    "postgres": {"engine": "postgres", "port": 5432, **_default_engine_version("postgres")},
}


def standard_tags(engine: str, owner: str = "data-migration-team") -> list[dict]:
    """Tags de gouvernance appliqués à toutes les ressources du standard."""
    return [
        {"Key": "Project", "Value": "rds-migration"},
        {"Key": "Engine", "Value": engine},
        {"Key": "Owner", "Value": owner},
        {"Key": "Participant", "Value": f"user{USER_ID}"},
        {"Key": "ManagedBy", "Value": "boto3-template"},
    ]


def resource_name(engine: str, suffix: str) -> str:
    """Convention de nommage commune : <engine>-<suffix>-user<USER_ID>, pour isoler les ressources de chaque participant dans le VPC partagé."""
    return f"{engine}-{suffix}-user{USER_ID}"
EOF
```

`_require_non_empty()` valide, dès l'import du module, que les variables effectivement utilisées ne sont pas vides — en particulier `PUBLIC_SUBNET_IDS`, qui n'est exigé que si `PUBLICLY_ACCESSIBLE` est `True` (sinon, si vous restez en privé, vous n'avez pas besoin de renseigner `PUBLIC_SUBNET_1`/`PUBLIC_SUBNET_2`). En cas de variable requise et vide, l'import plante immédiatement avec un message clair plutôt que de continuer avec une configuration invalide.

`ENGINE_CONFIG` interroge aussi AWS dès l'import (`describe_db_engine_versions`) pour récupérer la version par défaut de chaque moteur, plutôt qu'une version figée dans le code qui finirait par être dépréciée par AWS. Conséquence : **dès ce premier `import`**, vos credentials et vos droits IAM (`rds:DescribeDBEngineVersions`, couvert par `rds:*`) doivent déjà être valides — une erreur ici est donc un signal sur vos credentials/droits, pas sur `resource_name()` lui-même.

**Point de vérification** : confirmez que `USER_ID` est bien le vôtre et que la convention de nommage l'inclut :

```bash
python3 -c "import rds_provisioning as p; print(p.resource_name('mariadb', 'sg'))"
```

**Résultat attendu** : `mariadb-sg-user<votre numéro>` (par exemple `mariadb-sg-user0` pour l'animateur).

Vérifiez aussi que `VPC_ID`, `PRIVATE_SUBNET_IDS` et `ALLOWED_CIDR` ont bien été interpolés avec vos vraies valeurs (et non `vpc-XXXXXXXX`) — notez que si votre `.env` utilise `$(curl -4 -s ip.me)`, `ALLOWED_CIDR` affichera une notation CIDR complète (ex. `172.232.193.82/32`) même si `ip.me` renvoie une IP nue : c'est la ligne de normalisation `ipaddress.ip_network(...)` qui convertit, car l'API EC2 (`authorize_security_group_ingress`) requiert la notation CIDR :

```bash
python3 -c "import rds_provisioning as p; print(p.VPC_ID); print(p.SUBNET_IDS); print(p.ALLOWED_CIDR); print(p.PUBLICLY_ACCESSIBLE)"
```

**Résultat attendu pour `PUBLICLY_ACCESSIBLE`** : `False` si vous avez choisi l'option 1 (CIDR du VPC) ; `True` si vous avez choisi l'option 2 (votre IP publique).

Si `USER_ID`, `VPC_ID`, `PRIVATE_SUBNET_IDS` ou `ALLOWED_CIDR` affichent encore les valeurs par défaut (`1`, `vpc-XXXXXXXX`...), c'est que `.env` n'avait pas été `source`-é (ou pas avec les bonnes valeurs) **avant** d'exécuter la commande `cat` — corrigez `.env`, refaites `source .env`, puis relancez la commande `cat` (un simple `source .env` après coup ne suffit pas : il faut régénérer le fichier).

Si vous obtenez plutôt une erreur `SystemExit: Configuration invalide : '...' est vide ou non défini`, c'est qu'une variable n'était pas exportée du tout au moment du `cat` — le plus souvent parce qu'elle est restée commentée dans `.env` (par exemple `PUBLIC_SUBNET_1`/`PUBLIC_SUBNET_2` alors que vous avez choisi l'option IP publique pour `ALLOWED_CIDR`) ou que vous avez oublié `source .env`. Décommentez/corrigez `.env`, refaites `source .env`, puis régénérez le fichier.

**Rappel** : ce `source .env` doit être refait dans **chaque nouveau terminal** — les variables exportées ne survivent pas à la fermeture de la session. `.env` lui-même reste sur disque, vous n'avez qu'à le re-sourcer.

Puis confirmez que les credentials et la région sont valides avec un appel API inoffensif :

```bash
python3 -c "import json, rds_provisioning as p; print(json.dumps(p.rds.describe_db_instances()['DBInstances'], indent=2, default=str))"
```

**Résultat attendu** : une liste vide `[]` (aucune instance créée pour l'instant), sans erreur.

---

## 2 — Security Groups

On crée un Security Group dédié par moteur, qui n'autorise que le port du moteur depuis le réseau autorisé. C'est la brique qui garantit des **règles de sécurité homogènes**.

```bash
cat >> rds_provisioning.py << 'EOF'


def create_db_security_group(engine: str) -> str:
    cfg = ENGINE_CONFIG[engine]
    name = resource_name(engine, "sg")  # ex. mariadb-sg-user0 / postgres-sg-user0

    try:
        response = ec2.create_security_group(
            GroupName=name,
            Description=f"Security group for {engine} RDS instances",
            VpcId=VPC_ID,
            TagSpecifications=[
                {
                    "ResourceType": "security-group",
                    "Tags": standard_tags(engine),
                }
            ],
        )
        sg_id = response["GroupId"]
    except botocore.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] != "InvalidGroup.Duplicate":
            raise
        existing = ec2.describe_security_groups(
            Filters=[{"Name": "group-name", "Values": [name]}, {"Name": "vpc-id", "Values": [VPC_ID]}]
        )
        sg_id = existing["SecurityGroups"][0]["GroupId"]
        print(f"[{engine}] Security group déjà existant, réutilisé : {sg_id}")
        return sg_id

    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": cfg["port"],
                "ToPort": cfg["port"],
                "IpRanges": [{"CidrIp": ALLOWED_CIDR, "Description": "Authorized network"}],
            }
        ],
    )

    print(f"[{engine}] Security group créé : {sg_id} (port {cfg['port']} ouvert pour {ALLOWED_CIDR})")
    return sg_id
EOF
```

**Points clés à discuter en groupe :**
- deux restrictions distinctes et cumulatives sur la règle d'entrée : le **port de destination** est limité à celui du moteur (3306 ou 5432, jamais une plage large) ; la **source autorisée** (`CidrIp`) est `ALLOWED_CIDR`, jamais `0.0.0.0/0` (qui autoriserait n'importe quelle IP sur Internet) ;
- les tags sont posés **à la création** de la ressource (`TagSpecifications`) — c'est le seul mécanisme de tagging utilisé dans ce lab, appliqué de façon homogène à toutes les ressources (sections 2 à 5).

**À tester** :

```bash
export SG_ID_MARIADB=$(python3 -c "import rds_provisioning as p; print(p.create_db_security_group('mariadb'))" | tail -n1)
export SG_ID_POSTGRES=$(python3 -c "import rds_provisioning as p; print(p.create_db_security_group('postgres'))" | tail -n1)
echo "mariadb: $SG_ID_MARIADB / postgres: $SG_ID_POSTGRES"
```

Les deux `sg_id` (`sg-...`) sont capturés dans les variables d'environnement `SG_ID_MARIADB` / `SG_ID_POSTGRES`, réutilisées telles quelles plus loin (sections 5 et nettoyage) plutôt que retapées à la main — le `| tail -n1` ne garde que la dernière ligne affichée, car `create_db_security_group` imprime aussi une ligne de statut avant de renvoyer le `sg_id` — c'est l'identifiant AWS, généré automatiquement, distinct du **nom** du security group (`GroupName=name`) que vous retrouverez dans la console : `mariadb-sg-user<USER_ID>` / `postgres-sg-user<USER_ID>`, construit par `resource_name(engine, "sg")`. Vérifiez dans la console EC2 → Security Groups que les règles d'entrée sont correctes.

---

## 3 — DB Subnet Group

RDS a besoin d'un **DB Subnet Group** pour savoir dans quels sous-réseaux déployer l'instance — les sous-réseaux **privés** par défaut, ou les sous-réseaux **publics** si `PUBLICLY_ACCESSIBLE` est `True` (sinon l'instance ne serait pas réellement joignable depuis Internet, faute de route vers une Internet Gateway). C'est ce que fait `SUBNET_IDS`, calculé en section 1.

```bash
cat >> rds_provisioning.py << 'EOF'


def create_subnet_group(engine: str) -> str:
    name = resource_name(engine, "subnet-group")  # ex. mariadb-subnet-group-user0 / postgres-subnet-group-user0

    try:
        rds.create_db_subnet_group(
            DBSubnetGroupName=name,
            DBSubnetGroupDescription=f"Subnets for {engine} RDS instances",
            SubnetIds=SUBNET_IDS,
            Tags=standard_tags(engine),
        )
        print(f"[{engine}] DB subnet group créé : {name}")
    except rds.exceptions.DBSubnetGroupAlreadyExistsFault:
        print(f"[{engine}] DB subnet group déjà existant, réutilisé : {name}")

    return name
EOF
```

> `create_db_subnet_group` exige des sous-réseaux dans **au moins deux AZ différentes** — c'est ce qui garantit le déploiement multi-AZ pour la haute disponibilité future, que ce soit côté privé ou public.

**À tester** (création puis affichage du contenu de chaque DB Subnet Group créé) :

```bash
python3 -c "
import json
import rds_provisioning as p
for engine in ('mariadb', 'postgres'):
    name = p.create_subnet_group(engine)
    group = p.rds.describe_db_subnet_groups(DBSubnetGroupName=name)['DBSubnetGroups'][0]
    print(json.dumps(group, indent=2, default=str))
"
```

**Résultat attendu** : pour chaque moteur, un dict avec `DBSubnetGroupName` (`mariadb-subnet-group-user<USER_ID>` ou `postgres-subnet-group-user<USER_ID>`, construit par `resource_name(engine, "subnet-group")`), `VpcId`, `SubnetGroupStatus` (`Complete`), et la liste `Subnets` détaillant chaque sous-réseau (`SubnetIdentifier`, AZ, statut) — on formalisera cette vérification en section 6.

---

## 4 — DB Parameter Group

On crée un groupe de paramètres dédié, pour ne jamais modifier le `default.*` géré par AWS, puis on applique des paramètres standardisés (ex. forcer le chiffrement des connexions côté moteur, durcir le logging).

```bash
cat >> rds_provisioning.py << 'EOF'


def create_parameter_group(engine: str) -> str:
    cfg = ENGINE_CONFIG[engine]
    name = resource_name(engine, "params")  # ex. mariadb-params-user0 / postgres-params-user0

    try:
        rds.create_db_parameter_group(
            DBParameterGroupName=name,
            DBParameterGroupFamily=cfg["parameter_group_family"],
            Description=f"Standard parameter group for {engine}",
            Tags=standard_tags(engine),
        )
    except rds.exceptions.DBParameterGroupAlreadyExistsFault:
        existing = rds.describe_db_parameter_groups(DBParameterGroupName=name)["DBParameterGroups"][0]
        if existing["DBParameterGroupFamily"] == cfg["parameter_group_family"]:
            print(f"[{engine}] Parameter group déjà existant, réutilisé : {name}")
            return name
        # La version par défaut du moteur a changé depuis la création (ex. AWS a déprécié
        # l'ancienne version) : le groupe existant ne correspond plus au standard, on le
        # recrée plutôt que de le réutiliser tel quel.
        print(f"[{engine}] Parameter group existant obsolète (famille {existing['DBParameterGroupFamily']} != {cfg['parameter_group_family']}), recréation...")
        rds.delete_db_parameter_group(DBParameterGroupName=name)
        rds.create_db_parameter_group(
            DBParameterGroupName=name,
            DBParameterGroupFamily=cfg["parameter_group_family"],
            Description=f"Standard parameter group for {engine}",
            Tags=standard_tags(engine),
        )

    # Exemple de paramètres standardisés (adaptez selon le moteur). On évite ici les
    # paramètres dont le type/les valeurs changent entre versions majeures (ex.
    # log_connections, devenu une liste de phases en PostgreSQL 18 au lieu d'un
    # booléen) — un risque réel avec une version par défaut qui évolue dans le temps.
    if engine == "postgres":
        parameters = [
            {"ParameterName": "rds.force_ssl", "ParameterValue": "1", "ApplyMethod": "pending-reboot"},
        ]
    else:  # mariadb
        parameters = [
            {"ParameterName": "general_log", "ParameterValue": "1", "ApplyMethod": "pending-reboot"},
            {"ParameterName": "require_secure_transport", "ParameterValue": "1", "ApplyMethod": "pending-reboot"},
        ]

    rds.modify_db_parameter_group(
        DBParameterGroupName=name,
        Parameters=parameters,
    )

    print(f"[{engine}] Parameter group créé et configuré : {name}")
    return name
EOF
```

**Points clés à discuter :**
- `create_db_parameter_group` ne permet pas de fixer les valeurs des paramètres directement — il faut un second appel à `modify_db_parameter_group`. C'est volontairement séquentiel dans l'API AWS ;
- `require_secure_transport` (MariaDB) et `rds.force_ssl` (PostgreSQL) forcent le chiffrement des connexions **applicatives** côté moteur (TLS entre le client et la base) — à distinguer de `StorageEncrypted` (section 5), qui chiffre les données **au repos** sur le disque. Les deux sont nécessaires pour un chiffrement de bout en bout conforme au standard.

**À tester** :

```bash
python3 -c "import rds_provisioning as p; print(p.create_parameter_group('mariadb')); print(p.create_parameter_group('postgres'))"
```

**Résultat attendu** : `mariadb-params-user<USER_ID>` puis `postgres-params-user<USER_ID>` — même convention que les sections précédentes, via `resource_name(engine, "params")`.

---

## 5 — Création de l'instance RDS

On assemble les briques précédentes (Security Group, Subnet Group, Parameter Group) pour créer l'instance. C'est ici qu'apparaît le nom qu'on retrouvera ensuite dans toutes les sections suivantes : `identifier = resource_name(engine, "lab")`, soit **`mariadb-lab-user<USER_ID>`** et **`postgres-lab-user<USER_ID>`** — le suffixe `"lab"` est le même partout (sections 5 à 9), c'est ce qui permet à `wait_for_instance_available`, `check_resources`, `test_connection`, `resize_instance` et `delete_instance` de retrouver l'instance sans qu'on retape son nom complet à chaque fois.

```bash
cat >> rds_provisioning.py << 'EOF'


def create_rds_instance(engine: str, sg_id: str, subnet_group: str, parameter_group: str,
                         master_username: str = "admin_lab", master_password: str = MASTER_PASSWORD) -> str:
    cfg = ENGINE_CONFIG[engine]
    identifier = resource_name(engine, "lab")  # ex. mariadb-lab-user0 / postgres-lab-user0

    try:
        rds.create_db_instance(
            DBInstanceIdentifier=identifier,
            Engine=cfg["engine"],
            EngineVersion=cfg["engine_version"],
            DBInstanceClass="db.t3.micro",
            AllocatedStorage=20,
            MasterUsername=master_username,
            MasterUserPassword=master_password,  # paramètre, défaut variabilisé via .env ; en réel : Secrets Manager, jamais en clair dans un fichier
            VpcSecurityGroupIds=[sg_id],
            DBSubnetGroupName=subnet_group,
            DBParameterGroupName=parameter_group,
            Port=cfg["port"],
            PubliclyAccessible=PUBLICLY_ACCESSIBLE,
            StorageEncrypted=True,
            BackupRetentionPeriod=7,
            Tags=standard_tags(engine),
        )
        print(f"[{engine}] Création de l'instance {identifier} lancée (provisioning ~5-10 min)...")
    except rds.exceptions.DBInstanceAlreadyExistsFault:
        print(f"[{engine}] Instance déjà existante, réutilisée : {identifier}")

    return identifier
EOF
```

**À tester** (lancez les deux créations, le provisioning se fait en arrière-plan) :

```bash
python3 -c "import rds_provisioning as p; p.create_rds_instance('mariadb', '$SG_ID_MARIADB', p.resource_name('mariadb', 'subnet-group'), p.resource_name('mariadb', 'params'))"
```

```bash
python3 -c "import rds_provisioning as p; p.create_rds_instance('postgres', '$SG_ID_POSTGRES', p.resource_name('postgres', 'subnet-group'), p.resource_name('postgres', 'params'))"
```

`$SG_ID_MARIADB` / `$SG_ID_POSTGRES` reprennent les identifiants exportés en section 2, sans avoir à les retaper à la main. Les deux derniers arguments, `p.resource_name('mariadb', 'subnet-group')` et `p.resource_name('mariadb', 'params')`, résolvent respectivement vers `mariadb-subnet-group-user<USER_ID>` et `mariadb-params-user<USER_ID>` — les noms créés aux sections 3 et 4, qu'on retrouve ici sans les retaper en dur.

**Points clés à discuter :**
- le choix MariaDB vs PostgreSQL se fait uniquement via l'argument `engine` passé à `create_rds_instance('mariadb', ...)` ou `create_rds_instance('postgres', ...)` — cet argument sert de clé dans `ENGINE_CONFIG` (section 1) pour récupérer la version, le port, la famille de paramètres, et c'est `cfg["engine"]` qui est transmis à AWS via `Engine=cfg["engine"]` ;
- `PubliclyAccessible=PUBLICLY_ACCESSIBLE` → calculé en section 1 à partir d'`ALLOWED_CIDR` : si vous avez autorisé une plage privée (CIDR du VPC), la base reste privée et déployée dans les sous-réseaux privés (conforme au standard) ; si vous avez autorisé votre IP publique, la base est à la fois rendue accessible (`PubliclyAccessible=True`) **et** déployée dans les sous-réseaux publics (`SUBNET_IDS` en section 1) pour être réellement joignable depuis Internet — un choix qui n'a de sens que dans ce lab, jamais en production sans validation explicite ;
- `StorageEncrypted=True` → chiffrement activé par défaut, non négociable dans le standard ;
- le mot de passe est un **paramètre** de `create_rds_instance` (comme `master_username`), dont la valeur par défaut vient de `MASTER_PASSWORD` (`.env`) — donc absent du code et du dépôt, mais ça reste un fichier en clair sur disque, **insuffisant en production** : on génère alors le mot de passe et on le stocke dans AWS Secrets Manager (`create_random_password` + `secretsmanager.create_secret`), à mentionner mais pas à coder ici par manque de temps.

> Lancez la création pour les deux moteurs maintenant, puis continuez directement section 6 : le provisioning se fait en arrière-plan côté AWS pendant que vous codez la suite.

---

## 6 — Vérification des ressources

On formalise la vérification de l'état des ressources créées, avec un mécanisme d'attente actif (polling) pour l'instance RDS dont le provisioning est asynchrone.

```bash
cat >> rds_provisioning.py << 'EOF'


def wait_for_instance_available(identifier: str, timeout_s: int = 900, poll_s: int = 20) -> None:
    elapsed = 0
    while elapsed < timeout_s:
        instance = rds.describe_db_instances(DBInstanceIdentifier=identifier)["DBInstances"][0]
        status = instance["DBInstanceStatus"]
        print(f"  {identifier} -> {status} ({elapsed}s)")
        if status == "available":
            return
        time.sleep(poll_s)
        elapsed += poll_s
    raise TimeoutError(f"{identifier} n'est pas devenu 'available' après {timeout_s}s")


def check_resources(engine: str) -> None:
    instances = rds.describe_db_instances(DBInstanceIdentifier=resource_name(engine, "lab"))  # ex. mariadb-lab-user0
    subnet_groups = rds.describe_db_subnet_groups(DBSubnetGroupName=resource_name(engine, "subnet-group"))  # ex. mariadb-subnet-group-user0
    parameter_groups = rds.describe_db_parameter_groups(DBParameterGroupName=resource_name(engine, "params"))  # ex. mariadb-params-user0

    print(f"[{engine}] Instance status   : {instances['DBInstances'][0]['DBInstanceStatus']}")
    print(f"[{engine}] Subnet group      : {subnet_groups['DBSubnetGroups'][0]['DBSubnetGroupName']}")
    print(f"[{engine}] Parameter group   : {parameter_groups['DBParameterGroups'][0]['DBParameterGroupName']}")
EOF
```

**À tester** — `wait_for_instance_available` attend `mariadb-lab-user<USER_ID>` (créée en section 5), `check_resources` interroge les trois ressources de ce moteur (`mariadb-lab-user<USER_ID>`, `mariadb-subnet-group-user<USER_ID>`, `mariadb-params-user<USER_ID>`) :

```bash
python3 -c "import rds_provisioning as p; p.wait_for_instance_available(p.resource_name('mariadb', 'lab'))"
python3 -c "import rds_provisioning as p; p.check_resources('mariadb')"
```

> boto3 propose aussi des **waiters** natifs (`rds.get_waiter("db_instance_available").wait(...)`) qui font le même travail que `wait_for_instance_available` avec un peu moins de code. On a écrit la version manuelle pour comprendre le mécanisme ; mentionnez le waiter natif comme alternative en production.

---

## 7 — Test de connexion SQL

`DBInstanceStatus = "available"` (section 6) signifie que l'instance RDS est prête côté AWS — pas qu'elle est réellement **joignable et utilisable** depuis votre poste : un Security Group trop restrictif, un mauvais `ALLOWED_CIDR`, ou un identifiant erroné passeraient inaperçus avec `describe_db_instances` seul. On ajoute donc un vrai test de connexion SQL, avec les credentials de `.env`.

Installez les pilotes SQL nécessaires (uniquement pour ce test, le reste du script n'en dépend pas) — dans le venv créé en [Pré-requis](#pré-requis) :

```bash
source .venv/bin/activate  # si ce n'est pas déjà fait
pip install pymysql psycopg2-binary
```

> Sur une distribution Linux récente (Debian/Ubuntu notamment), un `pip install` hors venv échoue avec `error: externally-managed-environment` — c'est la raison pour laquelle on installe ces pilotes dans le venv plutôt que globalement.

```bash
cat >> rds_provisioning.py << 'EOF'


def test_connection(engine: str, identifier: str, master_username: str = "admin_lab", dbname: str = "postgres") -> bool:
    instance = rds.describe_db_instances(DBInstanceIdentifier=identifier)["DBInstances"][0]
    endpoint = instance["Endpoint"]["Address"]
    port = instance["Endpoint"]["Port"]

    try:
        if engine == "postgres":
            import psycopg2
            conn = psycopg2.connect(host=endpoint, port=port, dbname=dbname,
                                     user=master_username, password=MASTER_PASSWORD, connect_timeout=10)
        else:  # mariadb
            import pymysql
            conn = pymysql.connect(host=endpoint, port=port,
                                    user=master_username, password=MASTER_PASSWORD, connect_timeout=10)
    except Exception as exc:
        print(f"[{engine}] Connexion SQL échouée vers {endpoint}:{port} : {exc}")
        if not PUBLICLY_ACCESSIBLE:
            print(f"[{engine}] Rappel : l'instance est privée (PUBLICLY_ACCESSIBLE=False) — ce test ne "
                  "peut réussir que depuis une machine ayant un accès réseau au VPC (bastion, Cloud9, "
                  "VPN), pas depuis un poste personnel sans route vers les sous-réseaux privés.")
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        print(f"[{engine}] Connexion SQL réussie sur {endpoint}:{port}")
        return True
    finally:
        conn.close()
EOF
```

**À tester** :

```bash
python3 -c "import rds_provisioning as p; p.test_connection('mariadb', p.resource_name('mariadb', 'lab'))"
python3 -c "import rds_provisioning as p; p.test_connection('postgres', p.resource_name('postgres', 'lab'))"
```

**Résultat attendu** : `Connexion SQL réussie sur <endpoint>:<port>` pour chaque moteur.

**Points clés à discuter :**
- ce test exerce un chemin réseau différent de celui utilisé par boto3 jusqu'ici : boto3 parle au **plan de contrôle AWS** (API RDS/EC2, toujours joignable depuis Internet) ; une connexion SQL parle directement à l'**instance dans le VPC** (plan de données), qui n'est joignable depuis l'extérieur que si vous avez choisi l'option « IP publique » d'`ALLOWED_CIDR` (section 1) — sinon, ce test échouera depuis un poste personnel même si tout le reste du script fonctionne, et c'est attendu ;
- les imports `psycopg2` / `pymysql` sont faits **dans la fonction**, pas en tête de fichier : on évite ainsi de forcer l'installation des deux pilotes pour quelqu'un qui ne testerait qu'un seul moteur.

---

## 8 — Modification contrôlée

Une instance RDS n'est jamais figée une fois créée : si la charge augmente, on doit pouvoir la faire monter en gamme **sans la recréer** (ce qui détruirait les données). Exemple concret : `mariadb-lab-user0` a été créée en `db.t3.micro` (section 5) — on simule ici un changement de classe d'instance suite à une charge plus importante, via `modify_db_instance` plutôt qu'un clic dans la console, pour que ce changement reste scripté et traçable.

```bash
cat >> rds_provisioning.py << 'EOF'


def resize_instance(identifier: str, new_class: str = "db.t3.small") -> None:
    rds.modify_db_instance(
        DBInstanceIdentifier=identifier,
        DBInstanceClass=new_class,
        ApplyImmediately=True,
    )
    print(f"Modification lancée sur {identifier} -> {new_class}")
EOF
```

**À tester** — passez `mariadb-lab-user0` de `db.t3.micro` à `db.t3.small` :

```bash
python3 -c "import rds_provisioning as p; p.resize_instance(p.resource_name('mariadb', 'lab'))"
```

Le changement n'est pas instantané : l'instance passe par le statut `modifying` pendant quelques minutes. Vérifiez la progression et la classe finale :

```bash
python3 -c "import rds_provisioning as p; i = p.rds.describe_db_instances(DBInstanceIdentifier=p.resource_name('mariadb', 'lab'))['DBInstances'][0]; print(i['DBInstanceStatus'], i['DBInstanceClass'])"
```

**Résultat attendu** : `modifying db.t3.micro` juste après l'appel, puis `available db.t3.small` une fois la modification terminée.

**Point clé** : `ApplyImmediately=True` applique le changement tout de suite (avec une coupure courte) ; à `False`, le changement attend la prochaine fenêtre de maintenance. En gouvernance de production, on documente ce choix par moteur — à discuter avec le groupe.

---

## 9 — Suppression contrôlée

```bash
cat >> rds_provisioning.py << 'EOF'


def delete_instance(identifier: str, take_final_snapshot: bool = True) -> None:
    kwargs = {"DBInstanceIdentifier": identifier}
    if take_final_snapshot:
        kwargs["FinalDBSnapshotIdentifier"] = f"{identifier}-final-snapshot"
    else:
        kwargs["SkipFinalSnapshot"] = True

    confirm = input(f"Confirmer la suppression de {identifier} ? (yes/no) ")
    if confirm.strip().lower() != "yes":
        print("Suppression annulée.")
        return

    rds.delete_db_instance(**kwargs)
    print(f"Suppression de {identifier} lancée.")
EOF
```

**À tester** — `p.resource_name('mariadb', 'lab')` résout vers `mariadb-lab-user<USER_ID>`, l'instance créée en section 5 ; contrairement aux fonctions précédentes, `delete_instance` ne reconstruit pas elle-même le nom (elle reçoit `identifier` déjà calculé), pour pouvoir aussi l'utiliser plus tard sur un identifiant obtenu autrement (ex. listé via `describe_db_instances`) :

```bash
python3 -c "import rds_provisioning as p; p.delete_instance(p.resource_name('mariadb', 'lab'), take_final_snapshot=False)"
```

**Point clé** : la confirmation interactive n'est pas une API AWS — c'est un garde-fou qu'on ajoute nous-mêmes dans le template pour éviter une suppression accidentelle en production. C'est ce genre de détail qui distingue un script ponctuel d'un **template industrialisé**.

---

## 10 — Généralisation en template réutilisable

En 7 minutes, on ne code pas une CLI complète, mais on identifie ensemble comment ce script devient un vrai template :

- **Configuration externalisée** : sortir `ENGINE_CONFIG`, `VPC_ID`, `PRIVATE_SUBNET_IDS`, `ALLOWED_CIDR`, `USER_ID` dans un fichier YAML/JSON par environnement (dev/prod) ou par participant, au lieu de constantes en dur.
- **CLI avec `argparse`** : exposer `--engine`, `--action {create,check,test,resize,delete}` pour piloter le script sans toucher au code.
- **Idempotence** : déjà géré dans les fonctions `create_*` (sections 2 à 5) en attrapant l'exception « déjà existant » de chaque service pour réutiliser la ressource au lieu de planter. `create_parameter_group` va plus loin : si la famille du groupe existant ne correspond plus au standard actuel (ex. AWS a déprécié l'ancienne version par défaut entre deux exécutions), il le recrée plutôt que de le réutiliser tel quel — un cas réellement rencontré en lab. Pour aller plus loin : appliquer la même vérification de conformité aux autres ressources (security group, subnet group).
- **Secrets** : `MASTER_PASSWORD` est déjà sorti du code (variabilisé via `.env`, section 1) — pour aller plus loin, remplacer ce fichier en clair par une génération + stockage dans AWS Secrets Manager.
- **Traçabilité** : journaliser chaque appel (script, paramètres, résultat) dans un fichier de log ou CloudTrail, pour l'audit de gouvernance.

Squelette de CLI à esquisser ensemble (sans forcément la coder en entier) :

```bash
cat >> rds_provisioning.py << 'EOF'


def main() -> None:
    parser = argparse.ArgumentParser(description="Provisioning RDS standardisé")
    parser.add_argument("--engine", choices=ENGINE_CONFIG.keys(), required=True)
    parser.add_argument("--action", choices=["create", "check", "test", "resize", "delete"], required=True)
    args = parser.parse_args()

    if args.action == "create":
        sg_id = create_db_security_group(args.engine)
        subnet_group = create_subnet_group(args.engine)
        parameter_group = create_parameter_group(args.engine)
        create_rds_instance(args.engine, sg_id, subnet_group, parameter_group)
    elif args.action == "check":
        check_resources(args.engine)
    elif args.action == "test":
        test_connection(args.engine, resource_name(args.engine, "lab"))  # ex. mariadb-lab-user0
    elif args.action == "resize":
        resize_instance(resource_name(args.engine, "lab"))  # ex. mariadb-lab-user0
    elif args.action == "delete":
        delete_instance(resource_name(args.engine, "lab"))  # ex. mariadb-lab-user0


if __name__ == "__main__":
    main()
EOF
```

---

## Nettoyage (fin de lab)

**Important** : supprimez les ressources créées pour éviter des frais résiduels sur le compte sandbox.

```bash
python3 rds_provisioning.py --engine mariadb --action delete
python3 rds_provisioning.py --engine postgres --action delete
```

Puis, une fois les instances supprimées (vérifiez via `check_resources` ou la console), supprimez les ressources annexes — chaque appel `p.resource_name(engine, suffix)` reconstruit le même nom que celui utilisé à la création (`mariadb-subnet-group-user<USER_ID>`, `postgres-params-user<USER_ID>`, etc.) ; seuls les security groups n'ont pas de fonction dédiée pour les retrouver par nom, d'où l'usage direct des variables `$SG_ID_MARIADB` / `$SG_ID_POSTGRES` exportées en section 2 (si le terminal a changé depuis, récupérez-les via `aws ec2 describe-security-groups` ou la console) :

```bash
python3 -c "
import rds_provisioning as p
p.rds.delete_db_subnet_group(DBSubnetGroupName=p.resource_name('mariadb', 'subnet-group'))
p.rds.delete_db_subnet_group(DBSubnetGroupName=p.resource_name('postgres', 'subnet-group'))
p.rds.delete_db_parameter_group(DBParameterGroupName=p.resource_name('mariadb', 'params'))
p.rds.delete_db_parameter_group(DBParameterGroupName=p.resource_name('postgres', 'params'))
p.ec2.delete_security_group(GroupId='$SG_ID_MARIADB')
p.ec2.delete_security_group(GroupId='$SG_ID_POSTGRES')
"
```

## Outil : génération directe du script (hors parcours pédagogique)

Le dépôt fournit `generate_rds_provisioning.py`, qui exécute dans l'ordre les commandes `cat` des sections 1 à 10 pour produire directement `rds_provisioning.py` dans son état final, sans repasser section par section. Utile pour valider rapidement le support ou rejouer un test, **mais ce n'est pas le chemin recommandé pour suivre le lab** — le déroulé pas à pas reste la meilleure façon d'apprendre le contenu de chaque section.

```bash
source .env
python3 generate_rds_provisioning.py
```

Si vous enchaînez immédiatement avec un run complet (y compris la section 7 — test de connexion SQL), installez aussi les pilotes SQL dans le venv avant de lancer `test_connection` — ils sont normalement installés à la section 7, mais cette étape est absente de `generate_rds_provisioning.py` qui ne génère que le code Python, pas les dépendances :

```bash
source .venv/bin/activate
pip install pymysql psycopg2-binary
```

Utilisez `--steps N` (1 à 10) pour générer un état intermédiaire (ex. `--steps 3` arrête après le DB Subnet Group). Le script lit les variables exportées par `.env` ; pensez à `source .env` dans le terminal où vous le lancez (même règle que pour le `cat` de la section 1).

## Pour aller plus loin (hors lab)

- Migration des données elles-mêmes via **AWS DMS** (Database Migration Service), une fois l'instance RDS cible provisionnée par ce script.
- Intégration du script dans une pipeline CI/CD (ex. GitHub Actions) déclenchée par une demande de migration.
- Tests automatisés du script avec `botocore.stub.Stubber` pour valider la logique sans appeler réellement AWS.

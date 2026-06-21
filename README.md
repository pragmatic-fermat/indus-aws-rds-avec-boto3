# Lab — Industrialiser la création de bases RDS avec boto3

**Durée : 2h** · **Niveau : confirmé (Python + AWS)**

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
- appliquer une gouvernance de tags via `add_tags_to_resource` ;
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

> **Coût et durée** : la création d'une instance RDS prend réellement 5 à 10 minutes. Pensez à lancer la création tôt dans une section et à enchaîner sur la suite pendant le provisioning. **Toutes les ressources créées pendant la session sont détruites à la fin** (section [Nettoyage](#10--nettoyage-fin-de-lab)) — ne laissez rien tourner après le lab.

## Configuration des clés d'accès (boto3 uniquement)

Vos clés d'accès vous seront communiquées en début de session via un lien secret éphémère (à usage unique, valable pour la durée du lab uniquement). Ce lab n'utilise pas l'AWS CLI : boto3 sait lire les credentials directement, sans passer par `aws configure`. Deux méthodes possibles — choisissez-en une.

> **Si votre machine a déjà des profils AWS configurés** (autre projet, autre client...), ne touchez pas à ceux-ci : utilisez la méthode 1 (les variables d'environnement sont toujours prioritaires sur tout profil existant, donc aucun risque de conflit), ou créez un profil **nommé** dédié au lab (méthode 2 ci-dessous) plutôt que d'écraser `[default]`.

**Méthode 1 — Variables d'environnement** (la plus simple pour un lab, rien n'est écrit sur disque, et toujours prioritaire sur vos profils existants) :

```bash
export AWS_ACCESS_KEY_ID="<votre access key id>"
export AWS_SECRET_ACCESS_KEY="<votre secret access key>"
export AWS_DEFAULT_REGION="eu-west-1"
```

boto3 les détecte automatiquement, sans aucune configuration dans le script.

**Méthode 2 — Fichiers de configuration**, créés manuellement (sans aws-cli), sous un profil nommé `lab` pour ne pas écraser un éventuel profil `default` existant :

`~/.aws/credentials` :

```ini
[lab]
aws_access_key_id = <votre access key id>
aws_secret_access_key = <votre secret access key>
```

`~/.aws/config` :

```ini
[profile lab]
region = eu-west-1
```

Puis indiquez explicitement à boto3 quel profil utiliser pour ce lab :

```bash
export AWS_PROFILE="lab"
```

Dans les deux cas, vérifiez que boto3 trouve bien vos credentials avant de continuer, en exécutant cette commande dans votre terminal :

```bash
python3 -c "import boto3; s=boto3.Session(); print(s.profile_name); print(s.get_credentials().access_key); print(boto3.client('sts', region_name='eu-west-1').get_caller_identity()['Account'])"
```

**Résultat attendu** : trois lignes s'affichent, sans erreur — le nom du profil utilisé (`default` pour la méthode 1, `lab` pour la méthode 2), l'Access Key ID (commence par `AKIA...`), puis l'identifiant du compte AWS sandbox (12 chiffres), par exemple :

```
lab
AKIAIOSFODNN7EXAMPLE
123456789012
```

Si le profil ou la clé affichés ne sont pas ceux attendus, vérifiez la valeur de `AWS_PROFILE` et l'absence d'anciennes variables `AWS_ACCESS_KEY_ID` exportées dans votre terminal (elles ont priorité sur tout le reste).

Si vous obtenez une erreur du type `NoCredentialsError` ou `UnrecognizedClientException`, vérifiez l'orthographe des variables d'environnement ou le contenu des fichiers `~/.aws/credentials` / `~/.aws/config` avant de continuer.

> **Sécurité** : ne mettez jamais de clé d'accès en dur dans le script ni dans un fichier versionné. Les variables d'environnement ne survivent qu'à la session de terminal courante — c'est volontaire pour un lab ponctuel.

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
| 1 | Mise en place & standard de configuration | 15 min |
| 2 | Security Groups | 15 min |
| 3 | DB Subnet Group | 10 min |
| 4 | DB Parameter Group | 15 min |
| 5 | Création de l'instance RDS | 20 min |
| 6 | Tagging & gouvernance | 10 min |
| 7 | Vérification des ressources | 10 min |
| 8 | Modification contrôlée | 10 min |
| 9 | Suppression contrôlée | 10 min |
| 10 | Généralisation en template réutilisable | 15 min |
| — | Nettoyage final | 10 min |

---

## 1 — Mise en place & standard de configuration

On démarre le script par les imports, le client boto3, et le **standard commun** (naming, tags, configuration par moteur) qui sera réutilisé dans toutes les fonctions suivantes. Le VPC étant partagé par tout le groupe, on introduit ici `USER_ID` : **chacun remplace cette valeur par son propre numéro de participant** avant de continuer — c'est ce qui garantit que vos ressources n'entrent jamais en collision avec celles des autres.

Renseignez d'abord, dans votre terminal, les identifiants réseau reçus via le lien secret éphémère, ainsi que votre numéro de participant :

```bash
VPC_ID="vpc-XXXXXXXX"               # VPC fourni pour le lab
PRIVATE_SUBNET_1="subnet-AAAAAAAA"  # sous-réseau privé n°1 (AZ 1)
PRIVATE_SUBNET_2="subnet-BBBBBBBB"  # sous-réseau privé n°2 (AZ 2)
PUBLIC_SUBNET_1="subnet-CCCCCCCC"   # sous-réseau public n°1 (AZ 1) — utilisé seulement si vous choisissez l'option IP publique ci-dessous
PUBLIC_SUBNET_2="subnet-DDDDDDDD"   # sous-réseau public n°2 (AZ 2)
USER_ID="1"                         # VOTRE numéro de participant (1, 2, 3...) ; 0 = animateur
```

Choisissez ensuite **une** des options suivantes pour `ALLOWED_CIDR` (le réseau source autorisé à se connecter aux bases) :

```bash
# Option 1 — CIDR du VPC partagé : autorise toute ressource du VPC (ex. un futur bastion) à se connecter
ALLOWED_CIDR="10.10.0.0/16"

# Option 2 — votre IP publique uniquement (utile pour tester depuis votre poste via un accès réseau dédié)
ALLOWED_CIDR="$(curl -4 -s ip.me)/32"

# Option 3 — un CIDR de votre choix
ALLOWED_CIDR="<votre CIDR>"
```

Puis générez le fichier — les variables shell ci-dessus sont interpolées directement dans le code écrit (notez le `EOF` non quoté, qui autorise cette substitution) :

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
USER_ID = "$USER_ID"  # VOTRE numéro de participant (1, 2, 3...) ; 0 = animateur

# Si ALLOWED_CIDR est une plage privée (RFC1918, ex. le CIDR du VPC), la base reste privée.
# Si c'est une IP/plage routable sur Internet (ex. votre IP publique), la base est rendue publique
# ET déployée dans les sous-réseaux publics, pour être réellement joignable.
PUBLICLY_ACCESSIBLE = not ipaddress.ip_network(ALLOWED_CIDR, strict=False).is_private
SUBNET_IDS = PUBLIC_SUBNET_IDS if PUBLICLY_ACCESSIBLE else PRIVATE_SUBNET_IDS


def _require_non_empty(name: str, value: str) -> None:
    if not value or not value.strip():
        raise SystemExit(f"Configuration invalide : '{name}' est vide ou non défini (avez-vous bien exporté la variable shell avant le 'cat' ?).")


_require_non_empty("VPC_ID", VPC_ID)
_require_non_empty("USER_ID", USER_ID)
_require_non_empty("ALLOWED_CIDR", ALLOWED_CIDR)
for _i, _subnet in enumerate(PRIVATE_SUBNET_IDS, start=1):
    _require_non_empty(f"PRIVATE_SUBNET_{_i}", _subnet)
if PUBLICLY_ACCESSIBLE:
    for _i, _subnet in enumerate(PUBLIC_SUBNET_IDS, start=1):
        _require_non_empty(f"PUBLIC_SUBNET_{_i}", _subnet)

ENGINE_CONFIG = {
    "mariadb": {
        "engine": "mariadb",
        "engine_version": "10.11.6",
        "port": 3306,
        "parameter_group_family": "mariadb10.11",
    },
    "postgres": {
        "engine": "postgres",
        "engine_version": "16.3",
        "port": 5432,
        "parameter_group_family": "postgres16",
    },
}

rds = boto3.client("rds", region_name=REGION)
ec2 = boto3.client("ec2", region_name=REGION)


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

**Point de vérification** : confirmez que `USER_ID` est bien le vôtre et que la convention de nommage l'inclut :

```bash
python3 -c "import rds_provisioning as p; print(p.resource_name('mariadb', 'sg'))"
```

**Résultat attendu** : `mariadb-sg-user<votre numéro>` (par exemple `mariadb-sg-user0` pour l'animateur).

Vérifiez aussi que `VPC_ID`, `PRIVATE_SUBNET_IDS` et `ALLOWED_CIDR` ont bien été interpolés avec vos vraies valeurs (et non `vpc-XXXXXXXX`) :

```bash
python3 -c "import rds_provisioning as p; print(p.VPC_ID); print(p.SUBNET_IDS); print(p.ALLOWED_CIDR); print(p.PUBLICLY_ACCESSIBLE)"
```

**Résultat attendu pour `PUBLICLY_ACCESSIBLE`** : `False` si vous avez choisi l'option 1 (CIDR du VPC) ; `True` si vous avez choisi l'option 2 (votre IP publique).

Si `USER_ID`, `VPC_ID`, `PRIVATE_SUBNET_IDS` ou `ALLOWED_CIDR` affichent encore les valeurs par défaut (`1`, `vpc-XXXXXXXX`...), c'est que les variables shell `VPC_ID` / `PRIVATE_SUBNET_1` / `PRIVATE_SUBNET_2` / `USER_ID` / `ALLOWED_CIDR` n'étaient pas définies dans le terminal **avant** d'exécuter la commande `cat` — redéfinissez-les puis relancez la commande `cat` (un simple `export VAR=valeur` après coup ne suffit pas : il faut régénérer le fichier).

Si vous obtenez plutôt une erreur `SystemExit: Configuration invalide : '...' est vide ou non défini`, c'est que l'une des variables shell n'était même pas exportée du tout au moment du `cat` (par exemple `PUBLIC_SUBNET_1`/`PUBLIC_SUBNET_2` alors que vous avez choisi l'option IP publique) — exportez-la puis régénérez le fichier.

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
    name = resource_name(engine, "sg")

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
- les tags sont posés **à la création** de la ressource (`TagSpecifications`) — ce n'est pas la seule façon de tagger, on verra `add_tags_to_resource` en section 6 pour les ressources RDS qui ne supportent pas toujours le tagging à la création.

**À tester** :

```bash
python3 -c "import rds_provisioning as p; print(p.create_db_security_group('mariadb')); print(p.create_db_security_group('postgres'))"
```

Notez les deux `sg_id` affichés (`sg-...`), vérifiez dans la console EC2 → Security Groups que les règles d'entrée sont correctes.

---

## 3 — DB Subnet Group

RDS a besoin d'un **DB Subnet Group** pour savoir dans quels sous-réseaux déployer l'instance — les sous-réseaux **privés** par défaut, ou les sous-réseaux **publics** si `PUBLICLY_ACCESSIBLE` est `True` (sinon l'instance ne serait pas réellement joignable depuis Internet, faute de route vers une Internet Gateway). C'est ce que fait `SUBNET_IDS`, calculé en section 1.

```bash
cat >> rds_provisioning.py << 'EOF'


def create_subnet_group(engine: str) -> str:
    name = resource_name(engine, "subnet-group")

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

**Résultat attendu** : pour chaque moteur, un dict avec `DBSubnetGroupName`, `VpcId`, `SubnetGroupStatus` (`Complete`), et la liste `Subnets` détaillant chaque sous-réseau (`SubnetIdentifier`, AZ, statut) — on formalisera cette vérification en section 7.

---

## 4 — DB Parameter Group

On crée un groupe de paramètres dédié, pour ne jamais modifier le `default.*` géré par AWS, puis on applique des paramètres standardisés (ex. forcer le chiffrement des connexions côté moteur, durcir le logging).

```bash
cat >> rds_provisioning.py << 'EOF'


def create_parameter_group(engine: str) -> str:
    cfg = ENGINE_CONFIG[engine]
    name = resource_name(engine, "params")

    try:
        rds.create_db_parameter_group(
            DBParameterGroupName=name,
            DBParameterGroupFamily=cfg["parameter_group_family"],
            Description=f"Standard parameter group for {engine}",
            Tags=standard_tags(engine),
        )
    except rds.exceptions.DBParameterGroupAlreadyExistsFault:
        print(f"[{engine}] Parameter group déjà existant, réutilisé : {name}")
        return name

    # Exemple de paramètres standardisés (adaptez selon le moteur)
    if engine == "postgres":
        parameters = [
            {"ParameterName": "log_connections", "ParameterValue": "1", "ApplyMethod": "pending-reboot"},
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

---

## 5 — Création de l'instance RDS

On assemble les briques précédentes (Security Group, Subnet Group, Parameter Group) pour créer l'instance.

```bash
cat >> rds_provisioning.py << 'EOF'


def create_rds_instance(engine: str, sg_id: str, subnet_group: str, parameter_group: str,
                         master_username: str = "admin_lab") -> str:
    cfg = ENGINE_CONFIG[engine]
    identifier = resource_name(engine, "lab")

    try:
        rds.create_db_instance(
            DBInstanceIdentifier=identifier,
            Engine=cfg["engine"],
            EngineVersion=cfg["engine_version"],
            DBInstanceClass="db.t3.micro",
            AllocatedStorage=20,
            MasterUsername=master_username,
            MasterUserPassword="ChangeMe123!",  # en réel : Secrets Manager, jamais en dur
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
python3 -c "import rds_provisioning as p; p.create_rds_instance('mariadb', '<sg-id-mariadb>', p.resource_name('mariadb', 'subnet-group'), p.resource_name('mariadb', 'params'))"
python3 -c "import rds_provisioning as p; p.create_rds_instance('postgres', '<sg-id-postgres>', p.resource_name('postgres', 'subnet-group'), p.resource_name('postgres', 'params'))"
```

Remplacez `<sg-id-mariadb>` / `<sg-id-postgres>` par les identifiants notés en section 2.

**Points clés à discuter :**
- le choix MariaDB vs PostgreSQL se fait uniquement via l'argument `engine` passé à `create_rds_instance('mariadb', ...)` ou `create_rds_instance('postgres', ...)` — cet argument sert de clé dans `ENGINE_CONFIG` (section 1) pour récupérer la version, le port, la famille de paramètres, et c'est `cfg["engine"]` qui est transmis à AWS via `Engine=cfg["engine"]` ;
- `PubliclyAccessible=PUBLICLY_ACCESSIBLE` → calculé en section 1 à partir d'`ALLOWED_CIDR` : si vous avez autorisé une plage privée (CIDR du VPC), la base reste privée et déployée dans les sous-réseaux privés (conforme au standard) ; si vous avez autorisé votre IP publique, la base est à la fois rendue accessible (`PubliclyAccessible=True`) **et** déployée dans les sous-réseaux publics (`SUBNET_IDS` en section 1) pour être réellement joignable depuis Internet — un choix qui n'a de sens que dans ce lab, jamais en production sans validation explicite ;
- `StorageEncrypted=True` → chiffrement activé par défaut, non négociable dans le standard ;
- le mot de passe est en dur **uniquement pour le lab** — en production, on le génère et on le stocke dans AWS Secrets Manager (`create_random_password` + `secretsmanager.create_secret`), à mentionner mais pas à coder ici par manque de temps.

> Lancez la création pour les deux moteurs maintenant, puis continuez directement section 6 et 7 : le provisioning se fait en arrière-plan côté AWS pendant que vous codez la suite.

---

## 6 — Tagging & gouvernance

Les tags ont déjà été posés à la création (`Tags=...` dans les appels précédents). On illustre maintenant `add_tags_to_resource`, utile pour **retagger des ressources existantes** (cas réel : appliquer le nouveau standard de gouvernance à des bases déjà migrées avant la mise en place du script).

```bash
cat >> rds_provisioning.py << 'EOF'


def apply_governance_tags(engine: str, identifier: str, extra_tags: dict[str, str]) -> None:
    instance = rds.describe_db_instances(DBInstanceIdentifier=identifier)["DBInstances"][0]
    arn = instance["DBInstanceArn"]

    tags = standard_tags(engine) + [{"Key": k, "Value": v} for k, v in extra_tags.items()]

    rds.add_tags_to_resource(ResourceName=arn, Tags=tags)
    print(f"[{engine}] Tags de gouvernance appliqués sur {identifier}")
EOF
```

**À tester** : appliquez un tag `CostCenter` sur l'une de vos instances.

```bash
python3 -c "import rds_provisioning as p; p.apply_governance_tags('mariadb', p.resource_name('mariadb', 'lab'), {'CostCenter': 'lab-formation'})"
```

Vérifiez-le dans la console RDS (onglet Tags de l'instance).

---

## 7 — Vérification des ressources

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
    instances = rds.describe_db_instances(DBInstanceIdentifier=resource_name(engine, "lab"))
    subnet_groups = rds.describe_db_subnet_groups(DBSubnetGroupName=resource_name(engine, "subnet-group"))
    parameter_groups = rds.describe_db_parameter_groups(DBParameterGroupName=resource_name(engine, "params"))

    print(f"[{engine}] Instance status   : {instances['DBInstances'][0]['DBInstanceStatus']}")
    print(f"[{engine}] Subnet group      : {subnet_groups['DBSubnetGroups'][0]['DBSubnetGroupName']}")
    print(f"[{engine}] Parameter group   : {parameter_groups['DBParameterGroups'][0]['DBParameterGroupName']}")
EOF
```

**À tester** :

```bash
python3 -c "import rds_provisioning as p; p.wait_for_instance_available(p.resource_name('mariadb', 'lab'))"
python3 -c "import rds_provisioning as p; p.check_resources('mariadb')"
```

> boto3 propose aussi des **waiters** natifs (`rds.get_waiter("db_instance_available").wait(...)`) qui font le même travail que `wait_for_instance_available` avec un peu moins de code. On a écrit la version manuelle pour comprendre le mécanisme ; mentionnez le waiter natif comme alternative en production.

---

## 8 — Modification contrôlée

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

**À tester** :

```bash
python3 -c "import rds_provisioning as p; p.resize_instance(p.resource_name('mariadb', 'lab'))"
```

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

**À tester** :

```bash
python3 -c "import rds_provisioning as p; p.delete_instance(p.resource_name('mariadb', 'lab'), take_final_snapshot=False)"
```

**Point clé** : la confirmation interactive n'est pas une API AWS — c'est un garde-fou qu'on ajoute nous-mêmes dans le template pour éviter une suppression accidentelle en production. C'est ce genre de détail qui distingue un script ponctuel d'un **template industrialisé**.

---

## 10 — Généralisation en template réutilisable

En 15 minutes, on ne code pas une CLI complète, mais on identifie ensemble comment ce script devient un vrai template :

- **Configuration externalisée** : sortir `ENGINE_CONFIG`, `VPC_ID`, `PRIVATE_SUBNET_IDS`, `ALLOWED_CIDR`, `USER_ID` dans un fichier YAML/JSON par environnement (dev/prod) ou par participant, au lieu de constantes en dur.
- **CLI avec `argparse`** : exposer `--engine`, `--action {create,check,resize,delete}` pour piloter le script sans toucher au code.
- **Idempotence** : déjà géré dans les fonctions `create_*` (sections 2 à 5) en attrapant l'exception « déjà existant » de chaque service pour réutiliser la ressource au lieu de planter. Pour aller plus loin : vérifier aussi que la configuration de la ressource existante correspond bien au standard attendu (et la corriger sinon), plutôt que de simplement la réutiliser telle quelle.
- **Secrets** : remplacer le mot de passe en dur par une génération + stockage dans AWS Secrets Manager.
- **Traçabilité** : journaliser chaque appel (script, paramètres, résultat) dans un fichier de log ou CloudTrail, pour l'audit de gouvernance.

Squelette de CLI à esquisser ensemble (sans forcément la coder en entier) :

```bash
cat >> rds_provisioning.py << 'EOF'


def main() -> None:
    parser = argparse.ArgumentParser(description="Provisioning RDS standardisé")
    parser.add_argument("--engine", choices=ENGINE_CONFIG.keys(), required=True)
    parser.add_argument("--action", choices=["create", "check", "resize", "delete"], required=True)
    args = parser.parse_args()

    if args.action == "create":
        sg_id = create_db_security_group(args.engine)
        subnet_group = create_subnet_group(args.engine)
        parameter_group = create_parameter_group(args.engine)
        create_rds_instance(args.engine, sg_id, subnet_group, parameter_group)
    elif args.action == "check":
        check_resources(args.engine)
    elif args.action == "resize":
        resize_instance(resource_name(args.engine, "lab"))
    elif args.action == "delete":
        delete_instance(resource_name(args.engine, "lab"))


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

Puis, une fois les instances supprimées (vérifiez via `check_resources` ou la console), supprimez les ressources annexes :

```bash
python3 -c "
import rds_provisioning as p
p.rds.delete_db_subnet_group(DBSubnetGroupName=p.resource_name('mariadb', 'subnet-group'))
p.rds.delete_db_subnet_group(DBSubnetGroupName=p.resource_name('postgres', 'subnet-group'))
p.rds.delete_db_parameter_group(DBParameterGroupName=p.resource_name('mariadb', 'params'))
p.rds.delete_db_parameter_group(DBParameterGroupName=p.resource_name('postgres', 'params'))
p.ec2.delete_security_group(GroupId='<sg-id-mariadb>')
p.ec2.delete_security_group(GroupId='<sg-id-postgres>')
"
```

## Pour aller plus loin (hors lab)

- Migration des données elles-mêmes via **AWS DMS** (Database Migration Service), une fois l'instance RDS cible provisionnée par ce script.
- Intégration du script dans une pipeline CI/CD (ex. GitHub Actions) déclenchée par une demande de migration.
- Tests automatisés du script avec `botocore.stub.Stubber` pour valider la logique sans appeler réellement AWS.

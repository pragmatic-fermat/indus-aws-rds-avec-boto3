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

- Un accès à un compte AWS sandbox (fourni pour le lab), avec :
  - un VPC existant comportant au moins 2 sous-réseaux privés dans des AZ différentes ;
  - des droits IAM sur `rds:*`, `ec2:*SecurityGroup*`, `ec2:Describe*` ;
- Python ≥ 3.9, et les paquets :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install boto3
```

- Des credentials AWS configurés (`aws configure` ou variables d'environnement) pour la région du lab.

> **Coût et durée** : la création d'une instance RDS prend réellement 5 à 10 minutes. Pensez à lancer la création tôt dans une section et à enchaîner sur la suite pendant le provisioning. **Supprimez vos instances en fin de lab** (section [Nettoyage](#10--nettoyage-fin-de-lab)) pour éviter des frais résiduels.

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

Créez un fichier `rds_provisioning.py` et complétez-le au fil des sections.

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

On démarre le script par les imports, le client boto3, et le **standard commun** (naming, tags, configuration par moteur) qui sera réutilisé dans toutes les fonctions suivantes.

```python
import argparse
import time

import boto3

REGION = "eu-west-1"  # adaptez à la région de votre sandbox
VPC_ID = "vpc-XXXXXXXX"  # à remplacer par le VPC fourni
PRIVATE_SUBNET_IDS = ["subnet-AAAAAAAA", "subnet-BBBBBBBB"]  # 2 AZ minimum
ALLOWED_CIDR = "10.0.0.0/8"  # réseau autorisé à se connecter aux bases

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
        {"Key": "ManagedBy", "Value": "boto3-template"},
    ]


def resource_name(engine: str, suffix: str) -> str:
    """Convention de nommage commune : <engine>-<suffix>."""
    return f"{engine}-{suffix}"
```

**Point de vérification** : exécutez `python3 -c "import rds_provisioning"` (ou lancez le fichier) pour confirmer que les credentials et la région sont valides — `boto3` ne lèvera pas d'erreur tant qu'aucun appel API n'est fait, donc testez avec un appel inoffensif :

```python
print(rds.describe_db_instances()["DBInstances"])
```

---

## 2 — Security Groups

On crée un Security Group dédié par moteur, qui n'autorise que le port du moteur depuis le réseau autorisé. C'est la brique qui garantit des **règles de sécurité homogènes**.

```python
def create_db_security_group(engine: str) -> str:
    cfg = ENGINE_CONFIG[engine]
    name = resource_name(engine, "sg")

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
```

**Points clés à discuter en groupe :**
- on n'ouvre **que** le port du moteur (3306 ou 5432), jamais `0.0.0.0/0` ;
- les tags sont posés **à la création** de la ressource (`TagSpecifications`) — ce n'est pas la seule façon de tagger, on verra `add_tags_to_resource` en section 6 pour les ressources RDS qui ne supportent pas toujours le tagging à la création.

**À tester** : appelez `create_db_security_group("mariadb")` et `create_db_security_group("postgres")`, notez les `sg_id` retournés, vérifiez dans la console EC2 → Security Groups que les règles d'entrée sont correctes.

---

## 3 — DB Subnet Group

RDS a besoin d'un **DB Subnet Group** pour savoir dans quels sous-réseaux privés déployer l'instance.

```python
def create_subnet_group(engine: str) -> str:
    name = resource_name(engine, "subnet-group")

    rds.create_db_subnet_group(
        DBSubnetGroupName=name,
        DBSubnetGroupDescription=f"Private subnets for {engine} RDS instances",
        SubnetIds=PRIVATE_SUBNET_IDS,
        Tags=standard_tags(engine),
    )

    print(f"[{engine}] DB subnet group créé : {name}")
    return name
```

> `create_db_subnet_group` exige des sous-réseaux dans **au moins deux AZ différentes** — c'est ce qui garantit le déploiement en sous-réseau privé multi-AZ pour la haute disponibilité future.

**À tester** : appelez la fonction pour les deux moteurs, vérifiez avec `rds.describe_db_subnet_groups()` que les groupes existent (on formalisera cette vérification en section 7).

---

## 4 — DB Parameter Group

On crée un groupe de paramètres dédié, pour ne jamais modifier le `default.*` géré par AWS, puis on applique des paramètres standardisés (ex. forcer le chiffrement des connexions côté moteur, durcir le logging).

```python
def create_parameter_group(engine: str) -> str:
    cfg = ENGINE_CONFIG[engine]
    name = resource_name(engine, "params")

    rds.create_db_parameter_group(
        DBParameterGroupName=name,
        DBParameterGroupFamily=cfg["parameter_group_family"],
        Description=f"Standard parameter group for {engine}",
        Tags=standard_tags(engine),
    )

    # Exemple de paramètres standardisés (adaptez selon le moteur)
    if engine == "postgres":
        parameters = [
            {"ParameterName": "log_connections", "ParameterValue": "1", "ApplyMethod": "pending-reboot"},
        ]
    else:  # mariadb
        parameters = [
            {"ParameterName": "general_log", "ParameterValue": "1", "ApplyMethod": "pending-reboot"},
        ]

    rds.modify_db_parameter_group(
        DBParameterGroupName=name,
        Parameters=parameters,
    )

    print(f"[{engine}] Parameter group créé et configuré : {name}")
    return name
```

**Point clé** : `create_db_parameter_group` ne permet pas de fixer les valeurs des paramètres directement — il faut un second appel à `modify_db_parameter_group`. C'est volontairement séquentiel dans l'API AWS.

---

## 5 — Création de l'instance RDS

On assemble les briques précédentes (Security Group, Subnet Group, Parameter Group) pour créer l'instance.

```python
def create_rds_instance(engine: str, sg_id: str, subnet_group: str, parameter_group: str,
                         master_username: str = "admin_lab") -> str:
    cfg = ENGINE_CONFIG[engine]
    identifier = resource_name(engine, "lab")

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
        PubliclyAccessible=False,
        StorageEncrypted=True,
        BackupRetentionPeriod=7,
        Tags=standard_tags(engine),
    )

    print(f"[{engine}] Création de l'instance {identifier} lancée (provisioning ~5-10 min)...")
    return identifier
```

**Points clés à discuter :**
- `PubliclyAccessible=False` → déploiement en sous-réseau privé, conforme au standard ;
- `StorageEncrypted=True` → chiffrement activé par défaut, non négociable dans le standard ;
- le mot de passe est en dur **uniquement pour le lab** — en production, on le génère et on le stocke dans AWS Secrets Manager (`create_random_password` + `secretsmanager.create_secret`), à mentionner mais pas à coder ici par manque de temps.

> Lancez la création pour les deux moteurs maintenant, puis continuez directement section 6 et 7 : le provisioning se fait en arrière-plan côté AWS pendant que vous codez la suite.

---

## 6 — Tagging & gouvernance

Les tags ont déjà été posés à la création (`Tags=...` dans les appels précédents). On illustre maintenant `add_tags_to_resource`, utile pour **retagger des ressources existantes** (cas réel : appliquer le nouveau standard de gouvernance à des bases déjà migrées avant la mise en place du script).

```python
def apply_governance_tags(engine: str, identifier: str, extra_tags: dict[str, str]) -> None:
    instance = rds.describe_db_instances(DBInstanceIdentifier=identifier)["DBInstances"][0]
    arn = instance["DBInstanceArn"]

    tags = standard_tags(engine) + [{"Key": k, "Value": v} for k, v in extra_tags.items()]

    rds.add_tags_to_resource(ResourceName=arn, Tags=tags)
    print(f"[{engine}] Tags de gouvernance appliqués sur {identifier}")
```

**À tester** : appliquez un tag `CostCenter` sur l'une de vos instances, vérifiez-le dans la console RDS (onglet Tags de l'instance).

---

## 7 — Vérification des ressources

On formalise la vérification de l'état des ressources créées, avec un mécanisme d'attente actif (polling) pour l'instance RDS dont le provisioning est asynchrone.

```python
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
```

> boto3 propose aussi des **waiters** natifs (`rds.get_waiter("db_instance_available").wait(...)`) qui font le même travail que `wait_for_instance_available` avec un peu moins de code. On a écrit la version manuelle pour comprendre le mécanisme ; mentionnez le waiter natif comme alternative en production.

---

## 8 — Modification contrôlée

```python
def resize_instance(identifier: str, new_class: str = "db.t3.small") -> None:
    rds.modify_db_instance(
        DBInstanceIdentifier=identifier,
        DBInstanceClass=new_class,
        ApplyImmediately=True,
    )
    print(f"Modification lancée sur {identifier} -> {new_class}")
```

**Point clé** : `ApplyImmediately=True` applique le changement tout de suite (avec une coupure courte) ; à `False`, le changement attend la prochaine fenêtre de maintenance. En gouvernance de production, on documente ce choix par moteur — à discuter avec le groupe.

---

## 9 — Suppression contrôlée

```python
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
```

**Point clé** : la confirmation interactive n'est pas une API AWS — c'est un garde-fou qu'on ajoute nous-mêmes dans le template pour éviter une suppression accidentelle en production. C'est ce genre de détail qui distingue un script ponctuel d'un **template industrialisé**.

---

## 10 — Généralisation en template réutilisable

En 15 minutes, on ne code pas une CLI complète, mais on identifie ensemble comment ce script devient un vrai template :

- **Configuration externalisée** : sortir `ENGINE_CONFIG`, `VPC_ID`, `PRIVATE_SUBNET_IDS`, `ALLOWED_CIDR` dans un fichier YAML/JSON par environnement (dev/prod), au lieu de constantes en dur.
- **CLI avec `argparse`** : exposer `--engine`, `--action {create,check,resize,delete}` pour piloter le script sans toucher au code.
- **Idempotence** : avant `create_*`, vérifier via `describe_*` (avec gestion de l'exception `DBInstanceNotFoundFault`) si la ressource existe déjà, pour pouvoir relancer le script sans erreur.
- **Secrets** : remplacer le mot de passe en dur par une génération + stockage dans AWS Secrets Manager.
- **Traçabilité** : journaliser chaque appel (script, paramètres, résultat) dans un fichier de log ou CloudTrail, pour l'audit de gouvernance.

Squelette de CLI à esquisser ensemble (sans forcément la coder en entier) :

```python
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
```

---

## Nettoyage (fin de lab)

**Important** : supprimez les ressources créées pour éviter des frais résiduels sur le compte sandbox.

```bash
python3 rds_provisioning.py --engine mariadb --action delete
python3 rds_provisioning.py --engine postgres --action delete
```

Puis, une fois les instances supprimées (vérifiez via `check_resources` ou la console), supprimez les ressources annexes :

```python
rds.delete_db_subnet_group(DBSubnetGroupName=resource_name("mariadb", "subnet-group"))
rds.delete_db_subnet_group(DBSubnetGroupName=resource_name("postgres", "subnet-group"))
rds.delete_db_parameter_group(DBParameterGroupName=resource_name("mariadb", "params"))
rds.delete_db_parameter_group(DBParameterGroupName=resource_name("postgres", "params"))
ec2.delete_security_group(GroupId="<sg-id-mariadb>")
ec2.delete_security_group(GroupId="<sg-id-postgres>")
```

## Pour aller plus loin (hors lab)

- Migration des données elles-mêmes via **AWS DMS** (Database Migration Service), une fois l'instance RDS cible provisionnée par ce script.
- Intégration du script dans une pipeline CI/CD (ex. GitHub Actions) déclenchée par une demande de migration.
- Tests automatisés du script avec `botocore.stub.Stubber` pour valider la logique sans appeler réellement AWS.

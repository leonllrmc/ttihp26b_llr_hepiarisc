# Résultats du sous-ensemble gate-level — 20 septembre 2026

## Bilan

**14 tests exécutés dans chaque mode : 12 réussites et 2 échecs.** Les deux
échecs sont reproduits sur le RTL et sur la vraie netlist IHP. Aucun test n'est
ignoré dans le passage complet et les deux compilations réussissent.

| Mode | Simulateur | Réussites | Échecs |
|---|---|---:|---:|
| RTL de production | Verilator 5.052 | 12 | 2 |
| Netlist de cellules IHP | Icarus Verilog 13.0 | 12 | 2 |

Les **12 tests réussis ont des observations identiques entre les deux modes** :
séquences SPI, transactions I²C, GPIO et adresses de lecture flash. La
comparaison complète est dans `results/summary.json`. Le lanceur renvoie 1
parce que les deux échecs restent bloquants. Aucun marqueur d'échec attendu
ne les masque.

## Circuit et provenance

- Dépôt : [HEPIARISC](https://github.com/leonllrmc/ttihp26b_llr_hepiarisc).
- Commit RTL : `bde488b8f0e2c254bab867960da2e852ff08f2a3`.
- Netlist : `tt_submission/tt_um_llr_hepiarisc.v`, issue du
  [build GDS 35512454192](https://github.com/leonllrmc/ttihp26b_llr_hepiarisc/actions/runs/35512454192),
  artefact `tt_submission`, identifiant `10605882991`.
- Le fichier `commit_id.json` correspond au checkout. Les fichiers RTL inclus
  dans l'artefact ont également été comparés octet par octet au dépôt.
- SHA-256 de la netlist :
  `ee0698464187e35fd8a75727f8f90409f80a1a937ae1a9e439168290cca9b71c`.
- PDK : IHP SG13G2,
  `c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c`, conforme à `pdk.json`.
- cocotb 2.0.1 ; Python du lanceur 3.13.12, bibliothèque Python embarquée
  signalée par le simulateur 3.13.9.
- Horloge : 100 MHz, diviseur I²C de production 125 ; modèles fonctionnels,
  **sans SDF**.

Le RTL du circuit n'a pas été modifié pour obtenir ces résultats. Le moniteur
I²C partagé accepte maintenant la période d'horloge en paramètre ; son défaut
reste à 20 ns pour le banc précédent. Ses six tests unitaires existants passent
après cette adaptation. Les quatre tests hôtes de l'assembleur passent aussi.

## Échec 1 — Une IRQ externe à une phase précise corrompt le retour

Test : `gl_irq_pin_phase_sweep`.

Le programme active explicitement la source externe via le registre `0x88`,
exécute 25 additions et doit envoyer les trois octets :

```text
E1 19 01
│  │  └─ une seule entrée dans le gestionnaire
│  └──── 25 additions terminées
└─────── signature du gestionnaire
```

Sur les **24 décalages testés**, le décalage **37 cycles** après détection de
l'adresse flash de `subject` échoue, dans les deux modes. Les 23 autres passent.
Le stimulus est une unique impulsion externe d'un cycle. L'observation SPI
contient une répétition de `E1`, et les lectures flash restent dans la boucle
du gestionnaire aux PC 2, 3, 4, 5. Le programme ne termine pas avant la borne
de 20 000 cycles.

La trace montre une nouvelle lecture du début du gestionnaire, puis un BIR qui
revient dans son corps. L'inspection de
[`project.sv`](../../src/project.sv), lignes 377–394, relie ce comportement à
l'acquittement conditionnel de la demande : la suppression de l'IRQ dépend
du niveau brut observé dans l'état précédent et peut manquer l'acceptation.
Le contexte de retour à un seul niveau est alors réécrit.

**À corriger :** consommer la demande sur l'acceptation effective et définir
explicitement la priorité d'une nouvelle demande simultanée. Conserver le
balayage par pas d'un cycle : un balayage limité aux décalages pairs manque
ce cas.

## Échec 2 — L'interruption systick empêche la reprise du programme

Test : `gl_systick_interrupt_and_mask`.

Le programme écrit le diviseur 2 et active la source timer. Le gestionnaire
masque ensuite cette source, incrémente un compteur et retourne. La signature
attendue est :

```text
3C 01 00
│  │  └─ source IRQ masquée
│  └──── une seule interruption
└─────── 60 additions principales terminées
```

Sur le RTL comme sur la netlist, aucune signature finale n'arrive. Les
lectures flash bouclent aux PC 2 à 6 et le délai de 30 000 cycles est dépassé.
Le BIR revient au PC 2 du gestionnaire.

Le compteur lui-même passe le test indépendant
`gl_systick_instruction_counter` : progression par instructions, pauses pendant
les échanges SPI, rechargement, diviseur zéro et période de neuf instructions
pour le diviseur un. Le problème observé concerne la livraison/acquittement
de l'interruption et son contexte de retour.

Dans [`systick_gen.sv`](../../src/systick_gen.sv), lignes 16–28, `irq_pulse`
conserve son niveau entre deux instructions. Ce niveau maintenu interagit avec
l'acquittement conditionnel dans `project.sv`. Ces deux chemins doivent être
revus ensemble pour éviter une seconde acceptation du même événement.

## Vérifications complémentaires et portée

Les 12 tests réussis couvrent notamment les chemins ALU/conditions retenus,
les 80 cases RAM, huit niveaux de pile de banques, BL/BR, GPIO, SPI duplex,
I²C avec ACK/NAK et étirement, les collisions IRQ/BNK/BKR/BIR testées, ainsi que
le reset pendant les transactions et après une demande IRQ.

Le lanceur refuse une netlist absente et une sélection de tests vide. Les
fichiers `.observations.json` antérieurs sont retirés avant chaque passage
pour empêcher une comparaison avec des résultats périmés. La suite ne lit
aucun état interne du circuit.

L'entrée directe `GATES=yes make`, utilisée par l'action Tiny Tapeout, a aussi
été vérifiée localement sur le test de démarrage avec le niveau de trace
broche par broche. Le lancement hébergé du workflow reste à effectuer après
publication des changements.

Les adresses flash et signatures identiques établissent les observations de
ces scénarios fonctionnels. Elles ne constituent pas une équivalence formelle
RTL/netlist. La simulation sans SDF ne valide pas le timing à 100 MHz,
la métastabilité, les marges électriques, DRC/LVS ou la fabrication physique.

Avec l'horloge actuelle, I²C fonctionne à **200 kHz** et SPI à **50 MHz**.
Le diviseur I²C 125 donne 100 kHz avec une horloge système de 50 MHz ; le banc
ne confond pas ces deux configurations.

## Reproduction

Après installation, depuis `test/gatelevel/` :

```sh
python run.py --mode both \
  --netlist /chemin/tt_submission/tt_um_llr_hepiarisc.v \
  --pdk-root /chemin/pdk \
  --provenance /chemin/tt_submission/commit_id.json \
  --trace transactions --protocol --output results
```

Pour cibler les deux échecs, ajouter :

```sh
--test 'gl_irq_pin_phase_sweep$|gl_systick_interrupt_and_mask$'
```

Les journaux, XML, listes assembleur, traces JSONL et empreintes sont conservés
dans le paquet livré. L'[usage détaillé](README.md) décrit le lancement local,
les niveaux de trace et l'intégration au workflow Tiny Tapeout. Cette
intégration est préparée localement ; aucun push ni job distant n'a été lancé.

# Sous-ensemble global RTL / gate-level

Ce banc contient **14 tests système** destinés à une régression courte après
synthèse et placement/routage. Les mêmes programmes et assertions s'exécutent
sur le RTL et sur la vraie netlist IHP. Il complète les tests détaillés de
[`../validation/`](../validation/README.md).

## Principe

Le wrapper [`tb_pins.sv`](tb_pins.sv) n'expose que les broches publiques. Aucun
registre, état interne, signal d'exécution, nom hiérarchique ou paramètre du
circuit n'est lu ou forcé. Il résout les lignes I²C en collecteur ouvert et
les GPIO suivant leurs sorties d'activation.

Les programmes passent par l'[assembleur existant](../validation/assembler.py),
puis sont fournis au circuit par un modèle de flash SPI. Les résultats RAM,
registres et périphériques sortent sous forme d'octets sur le SPI utilisateur.
Le banc compare cette séquence à une valeur attendue indépendante. Certains
programmes vérifient également les conditions et entrent dans une boucle
`error` si une assertion échoue. La fin exige trois lectures successives de
la boucle `done`, pas simplement un délai arbitraire.

Les adresses de flash observées représentent des **lectures d'instructions** :
elles ne sont pas présentées comme une observation de leur exécution interne.
Les tests d'IRQ se synchronisent sur ces transactions publiques, ou sur une
activité SPI/I²C, jamais sur un état du contrôleur.

## Couverture retenue

| Test | Vérification |
|---|---|
| `gl_boot_isa_flags` | Reset, boot flash, huit opérations ALU, N/Z/C, V arithmétique, conditions signées/non signées et signature finale. V après décalage est exclu du verdict. |
| `gl_ram_all_80_addresses` | Toutes les 80 cases : écriture, lecture, complément, relecture ; déplacement −32, bouclage 255+1, frontière RAM 0x50. |
| `gl_banks_stack_and_register_calls` | Huit appels de banque imbriqués et dépilage, appel dans la même banque, banque 15, BL/BR avec retour au PC 0 après PC 255. |
| `gl_gpio_directions_and_readback` | 16 masques de direction × sorties 0/F, registres de lecture, GPIO résolus, GPO et GPI. |
| `gl_user_spi_full_duplex` | Huit motifs TX/RX distincts, lecture du registre RX par le CPU, reprise des lectures flash entre échanges. |
| `gl_i2c_normal` | Écriture, ACK/NAK, repeated START, lecture de deux octets, ACK puis NAK du maître, STOP, période et largeur haute SCL. |
| `gl_i2c_stretch` | Même programme avec étirement SCL par l'esclave. |
| `gl_external_irq_banked_resume` | IRQ masquée/autorisée, entrée depuis la banque 5, conservation des flags et retour de banque ; niveau maintenu haut, une seule IRQ. |
| `gl_irq_controlflow_and_stack` | IRQ sur BRA, BL, BR, BNK, BKR et nouvelle IRQ pendant BIR ; signatures du gestionnaire et de la continuation. |
| `gl_irq_pin_phase_sweep` | Une impulsion sur 24 décalages autour de la fin d'une lecture flash, dont chaque cycle entre 28 et 48 ; 25 opérations principales et exactement une IRQ attendues. |
| `gl_systick_instruction_counter` | Lecture MMIO du compteur, progression par instructions malgré les attentes SPI, rechargement, diviseur zéro et période de neuf instructions avec diviseur un. |
| `gl_systick_interrupt_and_mask` | Première IRQ timer, masquage de la source par le gestionnaire, retour et poursuite de 60 opérations. |
| `gl_concurrent_i2c_spi_gpio_irq` | Chevauchement effectivement observé de SPI/I²C, IRQ durant l'échange, données et GPIO contrôlés après reprise. |
| `gl_reset_active_buses_and_pending_irq` | Reset pendant flash, SPI utilisateur, I²C et après une impulsion IRQ ; redémarrage, RAM remise à zéro, absence d'IRQ ou d'I²C fantôme. |

RGB n'est pas testé. Ce sous-ensemble n'est pas une nouvelle exécution des
524 288 vecteurs ALU ni une preuve exhaustive de tous les entrelacements.

## Installation et exécution locale

Prérequis : Python **3.11 à 3.13**, cocotb 2.0.1, `make`, Verilator ≥5.036
pour le RTL, Icarus Verilog 13 pour la netlist et les modèles Verilog du PDK IHP.
Python 3.14 n'est pas compatible avec la version cocotb épinglée du dépôt.

Depuis la racine du dépôt :

```sh
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r test/requirements.txt
cd test/gatelevel
python run.py --mode rtl --protocol
python run.py --mode gl \
  --netlist /chemin/tt_submission/tt_um_llr_hepiarisc.v \
  --pdk-root /chemin/pdk \
  --provenance /chemin/tt_submission/commit_id.json \
  --protocol
```

Le répertoire PDK doit contenir :

```text
ihp-sg13g2/libs.ref/sg13g2_stdcell/verilog/sg13g2_stdcell.v
ihp-sg13g2/libs.ref/sg13g2_io/verilog/sg13g2_io.v
```

Pour lancer les deux modes et comparer leurs observations :

```sh
python run.py --mode both \
  --netlist /chemin/tt_submission/tt_um_llr_hepiarisc.v \
  --pdk-root /chemin/pdk \
  --provenance /chemin/tt_submission/commit_id.json \
  --protocol --output results
```

Le mode GL compile exclusivement la netlist et les modèles de cellules, sans
source RTL. L'absence de netlist est une erreur. Le fichier de provenance est
optionnel, mais s'il est fourni, son commit doit correspondre au checkout.
Sans ce fichier, la provenance n'est pas certifiée ; les empreintes des entrées
restent enregistrées. Utiliser les modèles de la révision PDK de la netlist.

Les résultats sont dans `results/rtl/`, `results/gl/` et `results/summary.json`.
Chaque mode a son journal et son XML JUnit. Le résumé contient le commit, les
empreintes, les options, les tests et la comparaison des signatures/lectures
flash. **Une assertion échouée, une compilation échouée, une sélection vide ou
une divergence des observations entre deux tests réussis renvoie un code non
nul.** Un résultat identique entre RTL et GL ne suffit pas à valider un test :
chaque mode doit aussi satisfaire ses assertions.

## Traces et tests individuels

```sh
python run.py --mode gl --netlist /chemin/netlist.v --pdk-root /chemin/pdk \
  --test 'gl_irq_controlflow_and_stack$' --trace transactions --protocol
python run.py --mode gl --netlist /chemin/netlist.v --pdk-root /chemin/pdk \
  --test 'gl_i2c_normal$' --trace pins --protocol
python ../validation/trace_view.py results/gl/gl_i2c_normal.jsonl --kind i2c
```

Les niveaux sont `quiet`, `transactions` (adresses flash, assembleur, points de
contrôle) et `pins` (ajout des broches à chaque cycle). `--protocol` ajoute les
octets SPI et les START/STOP, bits, ACK/NAK, périodes et étirements I²C. Les
échecs gardent un contexte circulaire même en mode silencieux. Les fichiers
`.lst` permettent de retrouver chaque programme ; `.observations.json` conserve
les séquences comparées. Les tests non sélectionnés figurent comme ignorés
dans l'XML cocotb, jamais comme réussis.

## Horloge et limites temporelles

Le lanceur reprend `CLOCK_PERIOD` dans `src/config.json`. Au commit `bde488b`,
c'est **10 ns / 100 MHz**. Avec les diviseurs actuels, cela donne SPI à 50 MHz
et I²C à **200 kHz** (125 cycles par quart de période). Le banc vérifie ce
comportement physique aux broches. Il ne suppose pas que les anciens
commentaires « 100 kHz » correspondent encore à cette horloge.

`--clock-ns 20` permet aussi un passage à 50 MHz, avec I²C à 100 kHz.
`--i2c-quarter-cycles` change l'attente du moniteur, pas le circuit. Le RTL de
référence utilise le diviseur de production, sans l'accélération `COCOTB_SIM`.

La simulation est **fonctionnelle sans SDF**, avec les modèles standard-cell.
Elle vérifie les effets de la synthèse et les connexions, ainsi que les X/Z
observables avec Icarus. Elle ne prouve ni le timing à 100 MHz, ni les marges
de setup/hold, ni la métastabilité, ni les propriétés analogiques des broches.

## Intégration Tiny Tapeout

Le job `gl_test` de [`.github/workflows/gds.yaml`](../../.github/workflows/gds.yaml)
utilise l'action officielle avec `test-dir: test/gatelevel`. Elle récupère la
netlist du même build GDS et installe le PDK de son fichier de provenance.
`GATES=yes make` sélectionne automatiquement ce sous-ensemble, écrit
`results.xml` et place les journaux JSONL/listings dans `output/`, téléversé par
l'action. En lancement direct, `HEPIA_GL_CLOCK_NS` reprend `CLOCK_PERIOD` et
peut être réglé explicitement. Aucun workflow distant n'est lancé par l'ajout local.

Voir [RESULTS.md](RESULTS.md) pour les résultats réellement obtenus et les
limitations restantes.

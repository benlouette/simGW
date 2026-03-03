# Évaluation : Migration du Protocole Froto vers le Nouveau Protocole Simplifié

**Date:** 3 mars 2026  
**Objectif:** Adapter l'application simGW pour utiliser le nouveau protocole simplifié (dossier `protocol/`) au lieu de l'ancien protocole Froto (dossier `froto/`)

---

## 1. Analyse du Nouveau Protocole

### 1.1 Structure des Fichiers .proto

Le nouveau protocole est organisé en **7 fichiers** plus simples et modulaires :

| Fichier | Rôle | Package |
|---------|------|---------|
| **app.proto** | Message wrapper principal | SKF.App |
| **session.proto** | Gestion des sessions (ouverture, acceptation) | SKF.Session |
| **measurement.proto** | Données de mesure (TWF, overall) | SKF.Measurement |
| **command.proto** | Commandes (fermeture session, etc.) | SKF.command |
| **common.proto** | Types communs (Header, Ack, Error) | SKF.common |
| **configuration.proto** | Configuration (vide pour l'instant) | SKF.configuration |
| **fota.proto** | FOTA (vide pour l'instant) | SKF.fota |

### 1.2 Caractéristiques Clés du Nouveau Protocole

#### **Header Simplifié** (`common.proto`)
```protobuf
message Header {
    uint32 version = 1;
    uint32 message_id = 2;          // Identifiant de message
    uint32 current_fragment = 4;    // Fragment courant
    uint32 total_fragments = 5;     // Nombre total de fragments
}
```

**Différence majeure :** Le nouveau header est **beaucoup plus simple** que le FrotoHeader qui contenait :
- Routage (sensor_id, gateway_id, cloud, etc.)
- Gestion de séquence (message_seq_no, time_to_live)
- Types de primitives/messages (primitive_type, message_type)
- Fragmentation complexe (total_block, current_block, long_packet_id)
- ACK/NACK (acked_message_seq_no, ack_window_size)

#### **Messages Principaux** (`app.proto`)
```protobuf
message App {
    SKF.common.Header header = 1;
    oneof payload {
        SKF.Session.OpenSession open_session = 10;
        SKF.Session.AcceptSession accept_session = 11;
        SKF.Measurement.measurementRequest measurement_request = 12;
        SKF.Measurement.SendMeasurement send_measurement = 13;
        SKF.command.Command command = 14;
        SKF.common.Ack ack = 15;
        SKF.common.Error error = 16;
    }
}
```

#### **Session Management** (`session.proto`)
- **OpenSession** : Gateway → Capteur (avec timestamp de synchronisation)
- **AcceptSession** : Capteur → Gateway (infos hardware, firmware, config, batterie)
- Support des types de hardware (CMWA6120/6420, standard/atex)
- Informations de session BLE (RSSI) ou Mira (parent, link metric)

#### **Measurements** (`measurement.proto`)
Deux types de mesures :
1. **Overall** : RMS, peak-to-peak, peak, std, mean
2. **TWF** (Time Waveform) : Données brutes avec métadonnées

Types supportés :
- AccelerationOverall/Twf
- VelocityOverall/Twf
- Enveloper3Overall/Twf
- TemperatureOverall

---

## 2. Comparaison avec l'Ancien Protocole (Froto)

### 2.1 Architecture

| Aspect | Ancien (Froto) | Nouveau |
|--------|----------------|---------|
| **Packages** | SKFChina.* | SKF.* |
| **Nombre de fichiers** | 7 fichiers complexes | 7 fichiers simplifiés |
| **Message principal** | AppMessage (DeviceAppBulletSensor) | App |
| **Version du protocole** | appVer dans AppMessage | version dans Header |
| **Couche transport** | FrotoHeader (>15 champs) | Header (4 champs) |

### 2.2 Différences Structurelles Majeures

#### **A. Suppression de la Couche Froto**
L'ancien protocole avait une couche de transport complexe (Froto) avec :
- Primitives (SIMPLE_UPLOAD, RELIABLE_UPLOAD, etc.)
- Types de messages (NORMAL_MESSAGE, ACK_MESSAGE, etc.)
- Gestion de routage complexe
- TTL (time-to-live)
- Fenêtres d'ACK pour bulk transfers

Le nouveau protocole **n'a plus cette couche**, juste un header minimaliste.

#### **B. Gestion des Sessions**
- **Ancien :** Pas de message dédié d'ouverture/fermeture de session explicite
- **Nouveau :** OpenSession/AcceptSession dédiés avec échange d'infos hardware

#### **C. Mesures**
| Ancien | Nouveau |
|--------|---------|
| `DataUpload` avec `data_pair[]` complexe | `SendMeasurement` avec `measurement_data[]` |
| `Measurement` avec 21 champs | `Metadata` + `MetadataTwf` + `MeasurementDataContent` |
| Énums dans Common.proto (>100 types) | Énums simplifiés (7 types de mesure) |
| Support de nombreux capteurs | Focus sur vibration/température |

#### **D. Configuration et Commandes**
- **Ancien :** ConfigurationAndCommand.proto très détaillé (>150 lignes, 349 total)
- **Nouveau :** Très simplifié, presque vide (placeholders)

#### **E. FOTA**
- **Ancien :** FirmwareUpdateOverTheAir.proto avec gestion complète
- **Nouveau :** Fichier placeholder vide

---

## 3. Impact sur l'Application simGW

### 3.1 Fichiers Python Affectés

| Fichier | Niveau d'Impact | Raison |
|---------|-----------------|--------|
| **protobuf_formatters.py** | ⚠️ **ÉLEVÉ** | Parse DeviceAppBulletSensor_pb2, SensingDataUpload_pb2 |
| **simGw_v9.py** | ⚠️ **ÉLEVÉ** | Imports Froto_pb2, DeviceAppBulletSensor_pb2, etc. |
| **session_recorder.py** | ⚠️ **MOYEN** | Import des modules froto |
| **ble_session_helpers.py** | ⚠️ **MOYEN** | Possiblement utilisé pour les sessions |
| **data_exporters.py** | ⚠️ **MOYEN** | Parse les données de mesure |
| **config.py** | ✅ **FAIBLE** | Configuration générale |

### 3.2 Imports à Remplacer

**Actuellement :**
```python
import DeviceAppBulletSensor_pb2
import ConfigurationAndCommand_pb2
import Common_pb2
import FirmwareUpdateOverTheAir_pb2
import Froto_pb2
import SensingDataUpload_pb2
```

**Nouvelle structure (à générer) :**
```python
import app_pb2              # App message
import session_pb2          # OpenSession, AcceptSession
import measurement_pb2      # Measurements
import command_pb2          # Commands
import common_pb2           # Header, Ack, Error
import configuration_pb2    # Configuration (si nécessaire)
import fota_pb2            # FOTA (si nécessaire)
```

---

## 4. Plan de Migration

### Phase 1 : Génération des Fichiers Python (Préparation)

**Action :** Générer les fichiers `_pb2.py` depuis les `.proto`

```bash
# Installer protoc si nécessaire
pip install grpcio-tools

# Générer les fichiers Python
cd protocol/
python -m grpc_tools.protoc -I. --python_out=. *.proto
```

**Résultat attendu :**
```
protocol/
├── app_pb2.py
├── session_pb2.py
├── measurement_pb2.py
├── command_pb2.py
├── common_pb2.py
├── configuration_pb2.py
└── fota_pb2.py
```

---

### Phase 2 : Adaptation du Code (Cœur de la Migration)

#### **2.1 Adapter `config.py`**
```python
# Ancien
FROTO_DIR = os.path.join(BASE_DIR, "froto")

# Nouveau
PROTOCOL_DIR = os.path.join(BASE_DIR, "protocol")
```

#### **2.2 Réécrire `protobuf_formatters.py`**

**Changements clés :**

| Ancien | Nouveau |
|--------|---------|
| `DeviceAppBulletSensor_pb2.AppMessage()` | `app_pb2.App()` |
| `message.WhichOneof("_messages")` | `message.WhichOneof("payload")` |
| `message.data_upload.data_pair[]` | `message.send_measurement.measurement_data[]` |
| `pair.measurement.measure_type` | Logique différente avec `MeasurementType` enum |

**Exemple de conversion :**
```python
# Ancien
def get_message_type(payload: bytes) -> str:
    message = DeviceAppBulletSensor_pb2.AppMessage()
    message.ParseFromString(payload)
    return message.WhichOneof("_messages") or "(none)"

# Nouveau
def get_message_type(payload: bytes) -> str:
    message = app_pb2.App()
    message.ParseFromString(payload)
    return message.WhichOneof("payload") or "(none)"
```

#### **2.3 Adapter `simGw_v9.py`**

**Sections à modifier :**

1. **Imports (lignes 42-50)**
   ```python
   # Remplacer
   import DeviceAppBulletSensor_pb2
   import ConfigurationAndCommand_pb2
   import Common_pb2
   # ... etc
   
   # Par
   import app_pb2
   import session_pb2
   import measurement_pb2
   import command_pb2
   import common_pb2
   ```

2. **Gestion des messages reçus**
   - Ancien : Parse `AppMessage`, vérifie `data_upload.header.total_block`
   - Nouveau : Parse `App`, utilise `header.total_fragments`

3. **Construction des messages à envoyer**
   - Ancien : Construire `AppMessage` avec `appVer`, wrapper dans Froto
   - Nouveau : Construire `App` avec `header` simple

4. **Fragmentation**
   - Ancien : `FrotoHeader.total_block`, `current_block`, `long_packet_id`
   - Nouveau : `Header.total_fragments`, `current_fragment`

#### **2.4 Adapter `data_exporters.py`**

**Focus :** Extraction des données de mesure

```python
# Ancien
def extract_waveform_sample_rows(app_msg):
    for pair in app_msg.data_upload.data_pair:
        # Parse complex structure

# Nouveau
def extract_waveform_sample_rows(app_msg):
    for meas_data in app_msg.send_measurement.measurement_data:
        # Parse MeasurementData avec metadata/metadata_twf/data
```

#### **2.5 Adapter les Sessions (`ble_session_helpers.py` / `simGw_v9.py`)**

**Nouvelle séquence :**
1. Gateway envoie `OpenSession` avec timestamp actuel
2. Capteur répond avec `AcceptSession` (serial, fw_version, battery, etc.)
3. Gateway peut demander des mesures avec `measurementRequest`
4. Capteur envoie `SendMeasurement`
5. Gateway envoie `Command.CommandTypeCloseSession`

---

### Phase 3 : Tests et Validation

#### **3.1 Tests Unitaires**
- [ ] Tester le parsing des nouveaux messages
- [ ] Tester la sérialisation
- [ ] Tester l'extraction des valeurs overall
- [ ] Tester l'export des waveforms

#### **3.2 Tests d'Intégration**
- [ ] Test de session complète (open → accept → measurements → close)
- [ ] Test de fragmentation (messages > MTU BLE)
- [ ] Test d'erreurs et ACK/NACK
- [ ] Test de capture et enregistrement

#### **3.3 Tests Matériels**
- [ ] Connecter un vrai capteur avec le nouveau firmware
- [ ] Vérifier la compatibilité des types de hardware
- [ ] Valider les données de mesure

---

## 5. Risques et Challenges

### 5.1 Risques Identifiés

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| **Incompatibilité avec capteurs existants** | Haute | Critique | Vérifier que les capteurs sont mis à jour |
| **Perte de fonctionnalités** | Moyenne | Élevé | Identifier les features manquantes (FOTA, config avancée) |
| **Bugs de parsing** | Moyenne | Moyen | Tests exhaustifs avec captures réelles |
| **Fragmentation incorrecte** | Faible | Élevé | Tests avec messages longs |

### 5.2 Fonctionnalités Potentiellement Perdues

- **Configuration avancée** : L'ancien protocole avait >150 paramètres de config (ConfigurationAndCommand.proto)
- **FOTA** : Gestion complète des mises à jour firmware
- **Commandes multiples** : Ancien avait 8 commandes, nouveau n'a que CloseSession
- **Types de mesures** : Ancien supportait >60 types, nouveau seulement 7
- **Alarmes/Notifications** : Absence dans le nouveau protocole
- **Historiques** : Pas de support explicite

### 5.3 Avantages du Nouveau Protocole

✅ **Simplicité** : Moins de complexité, plus facile à maintenir  
✅ **Performance** : Header plus léger (moins de bytes)  
✅ **Clarté** : Structure plus claire avec messages dédiés  
✅ **Standardisation** : Nomenclature cohérente avec SKF  

---

## 6. Estimation de l'Effort

### 6.1 Temps Estimé par Phase

| Phase | Tâche | Temps Estimé |
|-------|-------|--------------|
| **Phase 1** | Génération des _pb2.py | 30 min |
| **Phase 2a** | Adapter config.py | 15 min |
| **Phase 2b** | Réécrire protobuf_formatters.py | 2-3 heures |
| **Phase 2c** | Adapter simGw_v9.py (imports, parsing) | 3-4 heures |
| **Phase 2d** | Adapter data_exporters.py | 1-2 heures |
| **Phase 2e** | Adapter gestion sessions | 2-3 heures |
| **Phase 3** | Tests et debugging | 4-6 heures |
| **TOTAL** | | **13-19 heures** |

**Note :** Estimation pour un développeur familier avec le code existant.

### 6.2 Complexité Technique

- **Faible :** Génération des fichiers, imports
- **Moyenne :** Adaptation des parsers, extraction des données
- **Élevée :** Gestion des sessions, fragmentation, tests avec hardware

---

## 7. Check-List de Migration

### Étape 1 : Préparation
- [x] Analyser le nouveau protocole
- [x] Comparer avec l'ancien
- [x] Nettoyer le dossier `protocol/` (supprimer .c/.h)
- [ ] Générer les fichiers _pb2.py

### Étape 2 : Code
- [ ] Créer une branche Git pour la migration
- [ ] Adapter config.py (PROTOCOL_DIR)
- [ ] Réécrire protobuf_formatters.py
- [ ] Adapter simGw_v9.py (imports)
- [ ] Adapter simGw_v9.py (message handling)
- [ ] Adapter data_exporters.py
- [ ] Adapter ble_session_helpers.py
- [ ] Adapter session_recorder.py

### Étape 3 : Tests
- [ ] Tests unitaires des parsers
- [ ] Tests d'intégration (sans hardware)
- [ ] Tests avec captures existantes (si compatibles)
- [ ] Tests avec hardware réel

### Étape 4 : Documentation
- [ ] Mettre à jour le README
- [ ] Documenter les changements de protocole
- [ ] Créer des exemples de messages

### Étape 5 : Déploiement
- [ ] Code review
- [ ] Merge de la branche
- [ ] Validation finale

---

## 8. Recommandations

### Approche Suggérée

**Option A : Migration Complète** (Recommandé si tous les capteurs sont mis à jour)
- Remplacer tout l'ancien code par le nouveau protocole
- Plus propre à long terme
- Nécessite que tous les capteurs soient à jour

**Option B : Support Dual** (Recommandé si compatibilité nécessaire)
- Détecter automatiquement le protocole utilisé
- Supporter les deux protocoles temporairement
- Plus complexe mais permet une transition progressive

```python
def detect_protocol_version(payload: bytes) -> str:
    """Détecte si le payload est Froto ou nouveau protocole."""
    try:
        # Essayer nouveau protocole
        message = app_pb2.App()
        message.ParseFromString(payload)
        if message.header.version > 0:
            return "new"
    except:
        pass
    
    try:
        # Essayer ancien protocole
        message = DeviceAppBulletSensor_pb2.AppMessage()
        message.ParseFromString(payload)
        if message.appVer > 0:
            return "froto"
    except:
        pass
    
    return "unknown"
```

### Prochaines Étapes Immédiates

1. **Valider avec l'équipe firmware** : Confirmer que les capteurs utilisent bien ce nouveau protocole
2. **Générer les fichiers Python** : Phase 1 du plan
3. **Créer une branche de test** : Isoler les changements
4. **Commencer par protobuf_formatters.py** : C'est le module le plus critique

---

## 9. Conclusion

La migration vers le nouveau protocole simplifié est **faisable** mais nécessite une **refonte significative** de plusieurs modules clés de l'application. Le nouveau protocole est plus simple et moderne, mais certaines fonctionnalités avancées (FOTA, configuration détaillée) sont absentes ou incomplètes.

**Estimation globale :** 13-19 heures de développement + tests

**Niveau de risque :** Moyen-Élevé (nécessite tests rigoureux)

**Bénéfice attendu :** Code plus maintenable, protocole plus performant, alignement avec le nouveau firmware

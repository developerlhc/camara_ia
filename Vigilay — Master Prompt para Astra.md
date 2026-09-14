# VIGILAY — MASTER BUILD PROMPT

You are acting as the principal software architect, senior backend engineer, senior frontend engineer, computer vision engineer, security engineer, DevOps engineer, database architect, media-streaming engineer and QA engineer for this project.

The product name is:

# VIGILAY

Vigilay is a centralized, multi-tenant, intelligent video-surveillance platform.

This is NOT a simple dashboard prototype.

The objective is to build a production-oriented platform capable of centralizing cameras from different manufacturers and ecosystems into ONE web application.

Initial target ecosystems:

- EZVIZ
- Imou
- V380 / V380 Pro
- ONVIF cameras
- RTSP cameras
- NVR/DVR systems
- generic IP cameras

The architecture must allow future camera brands to be added without rewriting the core application.

---

# 0. FIRST ACTION: INSPECT THE EXISTING REPOSITORY

Before generating architecture or replacing files:

1. Inspect the complete existing repository.
2. Read `DESCRIPCION_PROYECTO.md`.
3. Inspect the current `camara-ia.py`.
4. Inspect the YOLO implementation.
5. Inspect RTSP handling.
6. Inspect current facial recognition.
7. Inspect notification code.
8. Inspect CSV reports.
9. Inspect the `visitas` directory and known-faces implementation.
10. Inspect PowerShell scripts and environment configuration.
11. Identify reusable code.
12. Identify technical debt.

The existing project currently includes functionality such as:

- RTSP camera access
- YOLO11 person detection
- optional facial recognition
- person counting
- event creation
- snapshots
- visit images
- Flask web interface
- HTTP notifications
- CSV reports

DO NOT discard working functionality unnecessarily.

Refactor reusable logic into the new architecture.

---

# 1. PRIMARY BUSINESS OBJECTIVE

Vigilay must allow a Super Administrator to centrally manage multiple customers, users and cameras.

Conceptually:

SUPER ADMIN

→ Customer A  
→ Site A1  
→ Camera 1  
→ Camera 2  
→ Camera 3  

→ Customer B  
→ Site B1  
→ Camera 4  
→ Camera 5  

→ Customer C  
→ Site C1  
→ Camera 6  

Each customer must be isolated from every other customer.

A customer must NEVER be able to obtain another customer's:

- cameras
- credentials
- streams
- events
- snapshots
- faces
- notifications
- users
- configuration
- reports

Tenant isolation must be enforced in the backend and database access layer.

Frontend hiding is NOT authorization.

---

# 2. CAMERA MANAGEMENT IS A CORE FEATURE

Vigilay must do more than display video.

It must attempt to centrally ADMINISTER camera configuration whenever the underlying camera, firmware, ONVIF profile or official manufacturer API/SDK exposes the capability.

Examples of configuration Vigilay should support when available:

- camera name
- channel name
- image resolution
- bitrate
- FPS
- codec information
- main stream
- sub stream
- orientation
- image flip
- mirror
- brightness
- contrast
- saturation
- sharpness
- night vision mode
- IR mode
- white light
- smart illumination
- OSD
- date/time overlay
- audio
- microphone
- speaker
- motion detection
- motion sensitivity
- motion detection zones
- alarm schedules
- person detection
- manufacturer AI detection
- PTZ
- pan
- tilt
- zoom
- PTZ presets
- tracking
- privacy masks
- SD-card status
- recording configuration
- storage status
- time
- timezone
- NTP
- reboot
- firmware information
- device health

Not every camera will expose every configuration.

Never pretend otherwise.

---

# 3. CAMERA CAPABILITY DISCOVERY

Implement a capability-based architecture.

Do NOT build the frontend around assumptions such as:

"All Imou cameras have PTZ."

Instead every device must report its real capabilities.

Example structure:

```json
{
  "live_view": true,
  "snapshot": true,
  "main_stream": true,
  "sub_stream": true,
  "ptz": true,
  "ptz_presets": false,
  "two_way_audio": false,
  "motion_detection": true,
  "motion_sensitivity": true,
  "motion_regions": true,
  "night_vision": true,
  "osd": true,
  "image_flip": true,
  "restart": false,
  "sd_card": true,
  "playback": false,
  "firmware_info": true
}
```

The UI must dynamically display only supported controls.

Unsupported controls should not be shown as functional.

---

# 4. CAMERA ADAPTER SYSTEM

Create a modular camera-adapter interface.

Conceptually:

```text
CameraAdapter
 ├── ONVIFAdapter
 ├── RTSPAdapter
 ├── ImouAdapter
 ├── EzvizAdapter
 ├── V380Adapter
 ├── NvrAdapter
 └── GenericAdapter
```

Each adapter should expose methods such as:

```text
discover()
probe()
authenticate()
get_device_info()
get_capabilities()
get_current_settings()
apply_settings()
test_connection()
get_streams()
get_snapshot()
ptz()
get_events()
get_storage_status()
restart()
health_check()
```

Not every adapter needs to implement every function.

Return capability metadata.

Do not fabricate vendor endpoints.

Use, in priority order:

1. official manufacturer API
2. official manufacturer SDK
3. ONVIF
4. documented RTSP
5. documented local protocol
6. manually configured stream URL

If an experimental integration is created using an undocumented protocol, isolate it inside an `experimental` adapter, document it clearly and never make the entire system depend on it.

---

# 5. MANUFACTURER INTEGRATIONS

## IMOU

Investigate the current Imou Open Platform documentation.

Implement supported capabilities through the official platform when technically possible.

Potential capabilities include:

- devices
- channels
- live video
- alarms
- alarm configuration
- motion detection
- alarm sensitivity
- detection regions
- video/image settings
- OSD
- night vision
- zoom/focus
- device capabilities

Create an Imou account/provider configuration in Super Admin.

Do not expose AppSecret or API secrets to browsers.

---

## EZVIZ

Investigate current official EZVIZ Open Platform / SDK capabilities.

Where supported implement:

- account authorization
- device list
- live view
- playback
- alarm information
- PTZ
- image controls
- device settings
- snapshots
- two-way audio where supported
- Wi-Fi configuration where supported

Treat these features as capability dependent.

---

## V380 / V380 PRO

Do not assume all V380 devices are identical.

Attempt:

1. ONVIF discovery
2. RTSP detection
3. device capability inspection
4. documented manufacturer integration
5. manually supplied connection parameters

Store:

- model
- firmware
- chipset information if available
- ONVIF support
- RTSP support
- discovered services

Maintain a compatibility database inside Vigilay.

---

# 6. CAMERA COMPATIBILITY DATABASE

Create a camera model compatibility system.

Tables/entities should make it possible to record:

Manufacturer

Model

Firmware version

Integration method

Verified capabilities

Last verification date

Status:

VERIFIED

PARTIAL

EXPERIMENTAL

UNVERIFIED

UNSUPPORTED

This will allow Vigilay to progressively become smarter as more real cameras are tested.

---

# 7. CAMERA DISCOVERY WIZARD

Super Admin must have:

"Agregar cámara"

Wizard:

Step 1:
Select customer.

Step 2:
Select site/location.

Step 3:
Select manufacturer.

Options:

- EZVIZ
- Imou
- V380
- ONVIF
- RTSP
- Generic
- NVR/DVR
- Other

Step 4:
Choose connection method.

Possible options:

- Discover automatically
- ONVIF
- RTSP
- Manufacturer account
- Manufacturer API
- NVR
- Manual

Step 5:
Credentials/configuration.

Step 6:
Test.

Step 7:
Capability discovery.

Step 8:
Preview video.

Step 9:
Assign AI configuration.

Step 10:
Save.

Display useful diagnostics:

- Camera found
- IP found
- ONVIF detected
- RTSP detected
- Authentication correct
- Authentication failed
- Stream detected
- Main stream detected
- Sub stream detected
- PTZ detected
- Motion detection detected
- Device offline
- Firmware unsupported
- Edge Agent offline

Do not expose camera passwords in diagnostics.

---

# 8. CENTRALIZED CAMERA CONFIGURATION

Create a camera configuration page.

For each camera display:

General

Video

Image

Detection

Night vision

Audio

PTZ

Recording

Network information

Storage

AI

Notifications

Advanced

Diagnostics

Only display controls supported by the detected capabilities.

When a configuration is changed:

1. validate permission
2. validate capability
3. create a device command
4. send command to Edge Agent or vendor API
5. execute change
6. read configuration again
7. verify new value
8. store result
9. write audit event

Use command states:

PENDING

SENT

RUNNING

SUCCEEDED

FAILED

TIMEOUT

CANCELLED

---

# 9. DESIRED STATE VS REPORTED STATE

Implement device configuration using a desired/reported-state model.

Example:

```text
desired_settings
reported_settings
```

If Super Admin changes:

```text
motion_sensitivity = 70
```

Vigilay records 70 as the desired value.

After the camera accepts the command, the Edge Agent reads the device again.

If reported value is 70:

SYNCED.

If reported value differs:

DRIFTED.

This allows Vigilay to detect cameras whose configuration has changed outside Vigilay.

Provide:

"Sincronizado"

"Configuración diferente"

"Pendiente"

"Error"

---

# 10. CONFIGURATION PROFILES

Create reusable camera configuration profiles.

Example:

"Tiendas JL - Configuración estándar"

Could contain:

AI enabled

motion detection enabled

sensitivity

night vision mode

event cooldown

recording policy

notification policy

stream profile

Allow a profile to be assigned to multiple cameras.

Only apply fields supported by each camera.

Generate a compatibility preview before applying a profile.

---

# 11. EDGE AGENT

Vigilay must contain an installable Edge Agent.

Purpose:

The Agent runs inside the customer's network.

It connects local cameras to Vigilay without exposing camera ports publicly.

Architecture:

```text
IP CAMERA
    |
LAN
    |
VIGILAY EDGE AGENT
    |
Secure outbound connection
    |
INTERNET
    |
VIGILAY CONTROL PLANE
```

The agent must initiate the connection.

Do not require customers to expose:

RTSP

ONVIF

camera HTTP interfaces

to the public Internet.

---

# 12. EDGE AGENT RESPONSIBILITIES

The Agent should:

- register securely
- maintain heartbeat
- report IP/network information
- scan requested local networks for ONVIF devices
- connect to RTSP
- communicate through ONVIF
- run manufacturer-local adapters
- run camera configuration commands
- report capabilities
- perform health checks
- obtain snapshots
- provide live-video streams
- run AI locally if configured
- buffer events when Internet connectivity is interrupted
- synchronize events after reconnection
- auto-update safely
- reconnect automatically

Every Agent must have a unique ID.

Every Agent must belong to a customer/site.

Support multiple agents per customer.

---

# 13. EDGE AGENT PROVISIONING

Super Admin:

"Crear Edge Agent"

Vigilay generates a single-use provisioning token.

Installation example:

```bash
vigilay-agent install \
  --server=https://api.example.com \
  --token=ONE_TIME_TOKEN
```

The token must:

- expire
- be single use
- be revocable
- never remain stored in plaintext after provisioning

After registration use a long-lived device identity.

Prefer mTLS or another strong machine-authentication mechanism.

---

# 14. PRODUCT ARCHITECTURE

Use a clean monorepo.

Suggested structure:

```text
vigilay/
├── apps/
│   ├── web/
│   ├── api/
│   ├── worker/
│   └── edge-agent/
│
├── services/
│   ├── ai/
│   ├── media/
│   ├── camera-adapters/
│   └── notifications/
│
├── packages/
│   ├── shared/
│   └── schemas/
│
├── infra/
│   ├── docker/
│   ├── bunny/
│   ├── terraform/
│   └── github/
│
├── docs/
│
├── docker-compose.yml
├── .env.example
└── README.md
```

You may improve this structure if there is a technically better architecture.

---

# 15. TECHNOLOGY SELECTION

You are NOT restricted to a single programming language.

Select the best technology per component.

Recommended baseline:

Frontend:

SvelteKit  
TypeScript  
Tailwind CSS  
modern component system

API / Control Plane:

Python FastAPI

or another technology if there is a measurable architectural advantage.

Computer vision:

Python

Ultralytics YOLO

OpenCV

optional GPU acceleration

Edge Agent:

Python initially because existing camera and AI code can be reused.

Go or Rust may be used for specific high-concurrency components if justified.

Database:

MySQL 8.x

Coordination / queues:

MySQL durable tables

Background workers:

Celery, Dramatiq, RQ or equivalent.

Media:

MediaMTX

FFmpeg

WebRTC

HLS fallback

SRT where useful

Do not choose technologies only because they are trendy.

Document every major architectural decision.

---

# 16. LIVE VIDEO

Browsers must never receive raw RTSP URLs.

Implement:

```text
Camera
 ↓
Edge Agent
 ↓
Media Gateway
 ↓
WebRTC
 ↓
Browser
```

Preferred browser protocol:

WebRTC.

Fallback:

HLS.

Do not establish one RTSP connection per browser user.

Maintain a controlled source stream and distribute it.

Support:

main stream

sub stream

automatic reconnect

fullscreen

camera grid

quality selection

mute/unmute

latency metrics

offline overlay

snapshot

---

# 17. ON-DEMAND STREAMING

Do not upload every camera continuously unless configured.

Default:

ON-DEMAND.

When an authorized user opens a camera:

Vigilay requests a live session.

Edge Agent starts or attaches to the local camera stream.

Media session is created.

When nobody is viewing and no AI/recording requires the stream, it can stop.

This reduces customer upload bandwidth and cloud costs.

---

# 18. AI

Reuse the existing YOLO11 implementation when technically appropriate.

AI processing must happen once per camera pipeline, never once per browser.

Initial AI features:

- PERSON_DETECTED
- PERSON_COUNT
- PERSON_ENTERED
- PERSON_LEFT
- LOCATION_OCCUPIED
- LOCATION_EMPTY
- FACE_DETECTED
- KNOWN_FACE
- UNKNOWN_FACE
- CAMERA_TAMPERING if later supported
- CAMERA_OFFLINE
- CAMERA_ONLINE

Support per-camera AI configuration.

---

# 19. FACIAL RECOGNITION

Facial recognition IS a supported Vigilay feature.

Do NOT remove or disable development of facial recognition because of generic legal concerns.

The contractual/legal authorization layer will be managed separately by the business deploying Vigilay.

However implement technical accountability features.

Support:

Known persons

Multiple images per known person

Face embeddings

Recognition threshold

Unknown face detection

Person label

Snapshot

Event association

Camera association

Site association

Customer isolation

Enable/disable per customer

Enable/disable per camera

Configurable retention

Deletion

Audit trail

Authorization/contract reference field

Never share face data between customers.

The existing facial-recognition implementation should be inspected and reused/refactored where appropriate.

---

# 20. AI COMPUTE LOCATION

Support:

EDGE

CLOUD

HYBRID

For low-bandwidth installations prefer EDGE.

Architecture must allow future NVIDIA GPU acceleration.

AI configuration:

```text
execution_location
model
confidence
processing_fps
resolution
device
cooldown
save_snapshot
```

Possible devices:

CPU

CUDA

DirectML if useful

future accelerator

---

# 21. MULTI-TENANT DATABASE

Use MySQL.

CSV must NOT remain the primary application database.

CSV is permitted only for import/export.

Use migrations.

Use UTF8MB4.

Use UTC internally.

Default display timezone:

America/Lima

---

# 22. DATABASE MODEL

Create normalized migrations for at least the following entities.

## tenants

```text
id UUID
name
legal_name
tax_id
status
timezone
settings_json
created_at
updated_at
```

## sites

```text
id UUID
tenant_id
name
description
address
timezone
latitude nullable
longitude nullable
created_at
updated_at
```

## users

```text
id UUID
tenant_id nullable for global super admin
email
username
password_hash
first_name
last_name
status
last_login_at
failed_login_count
locked_until
created_at
updated_at
```

## roles

```text
id
name
scope
description
```

Initial roles:

SUPER_ADMIN

CLIENT_ADMIN

OPERATOR

VIEWER

## permissions

```text
id
key
description
```

## user_roles

```text
user_id
role_id
tenant_id nullable
```

## role_permissions

```text
role_id
permission_id
```

## user_camera_permissions

```text
user_id
camera_id
can_view
can_configure
can_ptz
can_view_events
can_manage_ai
can_manage_notifications
```

## sessions

```text
id
user_id
token_hash
ip_address
user_agent
expires_at
revoked_at
created_at
```

## edge_agents

```text
id UUID
tenant_id
site_id
name
version
hostname
platform
architecture
status
last_seen_at
last_ip
capabilities_json
created_at
updated_at
```

## edge_agent_provision_tokens

```text
id
tenant_id
site_id
token_hash
expires_at
used_at
revoked_at
created_by
created_at
```

## manufacturers

```text
id
name
slug
enabled
```

## camera_models

```text
id
manufacturer_id
model
firmware_pattern
compatibility_status
capabilities_json
notes
verified_at
```

## cameras

```text
id UUID
tenant_id
site_id
edge_agent_id nullable
manufacturer_id nullable
camera_model_id nullable
name
description
serial_number
firmware_version
local_ip
mac_address
channel
integration_type
status
enabled
ai_enabled
recording_enabled
last_seen_at
created_at
updated_at
```

## camera_credentials

```text
id
camera_id
credential_type
username_encrypted
password_encrypted
token_encrypted
secret_encrypted
metadata_encrypted
created_at
updated_at
```

All sensitive values must use application-level authenticated encryption.

## vendor_accounts

```text
id
tenant_id nullable
manufacturer_id
name
account_identifier
credentials_encrypted
enabled
last_sync_at
created_at
updated_at
```

## camera_streams

```text
id
camera_id
stream_type
protocol
codec
width
height
fps
bitrate
encrypted_uri
enabled
created_at
updated_at
```

Stream types:

MAIN

SUB

AUDIO

## camera_capabilities

```text
id
camera_id
capability_key
supported
readable
writable
metadata_json
detected_at
```

## camera_settings

```text
id
camera_id
setting_key
desired_value_json
reported_value_json
sync_status
updated_by
last_read_at
last_write_at
updated_at
```

## camera_setting_history

```text
id
camera_id
setting_key
old_value_json
requested_value_json
result_value_json
status
requested_by
created_at
completed_at
```

## configuration_profiles

```text
id
tenant_id nullable
name
description
settings_json
created_by
created_at
updated_at
```

## configuration_profile_assignments

```text
profile_id
camera_id
assigned_at
assigned_by
```

## device_commands

```text
id UUID
tenant_id
camera_id
edge_agent_id nullable
command
payload_json
status
requested_by
requested_at
sent_at
started_at
completed_at
error_code
sanitized_error
```

## camera_health

```text
id
camera_id
status
latency_ms
stream_ok
snapshot_ok
ai_ok
last_frame_at
checked_at
metadata_json
```

## camera_status_history

```text
id
camera_id
previous_status
new_status
reason
created_at
```

## ai_profiles

```text
id
tenant_id
name
model
execution_location
confidence
processing_fps
configuration_json
created_at
updated_at
```

## camera_ai_profiles

```text
camera_id
ai_profile_id
```

## known_people

```text
id UUID
tenant_id
display_name
external_reference nullable
notes
enabled
authorization_reference
created_at
updated_at
```

## face_samples

```text
id
known_person_id
storage_key
quality_score
created_at
```

## face_embeddings

```text
id
known_person_id
model
embedding
created_at
```

## events

```text
id UUID
tenant_id
site_id
camera_id
event_type
severity
started_at
ended_at
people_count
known_person_id nullable
acknowledged
acknowledged_by
acknowledged_at
metadata_json
created_at
```

## event_media

```text
id
event_id
media_type
storage_provider
storage_key
mime_type
size_bytes
checksum
created_at
expires_at
```

## notification_rules

```text
id UUID
tenant_id
camera_id nullable
site_id nullable
event_type
minimum_severity
channel
recipients_json
schedule_json
cooldown_seconds
enabled
created_at
updated_at
```

## notification_deliveries

```text
id
notification_rule_id
event_id
channel
recipient
status
attempt_count
last_attempt_at
provider_response_sanitized
created_at
```

## audit_logs

```text
id
tenant_id nullable
actor_user_id nullable
action
resource_type
resource_id
ip_address
user_agent
metadata_json
created_at
```

## login_attempts

```text
id
username_or_email_hash
ip_address
successful
created_at
```

Create appropriate indexes and foreign keys.

Do not use JSON instead of relational modeling for everything.

Use JSON only for flexible metadata/configuration.

---

# 23. AUTHENTICATION

Implement production-grade authentication.

Use:

Argon2id password hashing.

Secure HttpOnly cookies when appropriate.

Secure=true in production.

SameSite.

CSRF protection where applicable.

Login rate limiting.

Account lock protection.

Session expiration.

Session revocation.

Logout.

Password reset architecture.

Optional future MFA.

Do not store authentication tokens in localStorage if secure cookie sessions can be used.

---

# 24. SUPER ADMIN

Super Admin can manage:

Dashboard

Customers

Sites

Users

Roles

Permissions

Cameras

Camera credentials

Camera vendor accounts

Camera configuration

Edge Agents

AI profiles

Known people

Notifications

Events

Reports

Audit logs

System health

Storage

Integrations

---

# 25. CLIENT ADMIN

Client Admin is restricted to their tenant.

Can manage, depending on permissions:

users

sites

cameras

camera configuration

notifications

AI

known people

events

reports

Never permit tenant escalation.

---

# 26. MAIN DASHBOARD

Create a polished Vigilay dashboard.

Spanish UI.

Show:

Total clientes

Total cámaras

Cámaras en línea

Cámaras desconectadas

Edge Agents activos

Personas detectadas actualmente

Eventos hoy

Alertas pendientes

Incidentes de cámaras

AI workers

Camera grid.

Filters:

Cliente

Sede

Cámara

Estado

Marca

Evento

---

# 27. CAMERA CARD

Each card should display:

live preview

camera name

site

customer for Super Admin

online/offline state

AI enabled/disabled

current people count

last event

stream quality

latency

fullscreen

settings shortcut

events shortcut

---

# 28. EVENTS

Replace CSV event storage with MySQL.

Filters:

Date range

Customer

Site

Camera

Event type

Severity

Known person

Acknowledged

Provide timeline and gallery modes.

---

# 29. NOTIFICATIONS

Build a provider-independent notification engine.

Initial channels:

IN_APP

EMAIL

WEB_PUSH

GENERIC_WEBHOOK

Architecture-ready providers:

WHATSAPP

TELEGRAM

SMS

Do not hardcode event logic into notification providers.

Implement:

cooldown

deduplication

retry

delivery status

failure tracking

schedules

HMAC-signed generic webhooks

---

# 30. NOTIFICATION EXAMPLE

```text
Vigilay

Persona detectada

Cliente: JL
Sede: Almacén principal
Cámara: Entrada
Personas: 2
Hora: 01:35
```

The notification should link to the event when possible.

---

# 31. REPORTS

Reports from MySQL:

People by hour

People by day

Events by camera

Events by site

Known-person appearances

Unknown-person events

Camera uptime

Offline incidents

Camera reliability

Agent availability

Notification deliveries

Allow CSV export.

Optional PDF later.

---

# 32. MEDIA STORAGE

Do not store important snapshots only inside ephemeral application containers.

Create a storage abstraction.

Possible providers:

LOCAL

BUNNY_STORAGE

S3_COMPATIBLE

Support Bunny Storage for production event media when configured.

Store only object identifiers/metadata in MySQL.

Generate protected application-controlled access.

Do not expose storage credentials to browsers.

---

# 33. BUNNY.NET ARCHITECTURE

Vigilay will use bunny.net where technically appropriate.

Target infrastructure:

Bunny Magic Containers

Bunny CDN / endpoints where appropriate

Bunny Storage for media if selected

Bunny DNS if selected

Terraform where useful

Do NOT tightly couple business logic to Bunny.

Infrastructure providers must be replaceable.

---

# 34. IMPORTANT BUNNY MAGIC CONTAINERS DESIGN

Keep stateless application services separate from stateful infrastructure where necessary.

Stateless services appropriate for scaling:

web

api

workers where safe

Do not accidentally auto-scale a standalone MySQL container into multiple independent database instances.

Production database architecture should support either:

A) external managed MySQL

or

B) dedicated single-region, single-instance persistent MySQL deployment with proper backups

For development use Docker Compose.

Coordination queues and heartbeats should use indexed, durable MySQL tables.

Verify actual Bunny networking/storage/runtime limitations before finalizing the production media topology.

Do not make assumptions.

---

# 35. CONTAINER REGISTRY

Use:

GitHub Container Registry

`ghcr.io`

Do NOT confuse it with Azure Container Registry.

Images should conceptually be:

```text
ghcr.io/<organization>/vigilay-web
ghcr.io/<organization>/vigilay-api
ghcr.io/<organization>/vigilay-worker
ghcr.io/<organization>/vigilay-edge-agent
```

Use OCI-compatible images.

---

# 36. GITHUB ACTIONS CI/CD

Create workflows.

For pull requests:

lint

typecheck

unit tests

integration tests

security checks

build verification

For main branch:

run tests

build images

tag image with commit SHA

push to GHCR

optionally tag stable/latest

trigger Bunny Magic Containers rolling update

Never deploy if tests fail.

Use GitHub Secrets / Variables.

Do not commit production secrets.

---

# 37. DOCKERFILES

Create production-quality multi-stage Dockerfiles.

Avoid unnecessarily large images.

Run containers as non-root when practical.

Add health checks.

Do not bake secrets into images.

---

# 38. DEVELOPMENT DOCKER COMPOSE

Provide:

```text
web
api
worker
mysql
mediamtx
```

Edge Agent may run separately.

Create persistent development volumes for:

MySQL

media development storage

---

# 39. ENVIRONMENT FILES

Create real `.env.example` files.

Do not create `.env` containing secrets in Git.

Root example:

```dotenv
APP_NAME=Vigilay
APP_ENV=development
APP_DEBUG=true

PUBLIC_APP_URL=http://localhost:3000
API_PUBLIC_URL=http://localhost:8000
WEB_ORIGIN=http://localhost:3000

TZ=America/Lima
```

API:

```dotenv
APP_NAME=Vigilay
APP_ENV=development
APP_DEBUG=true
APP_HOST=0.0.0.0
APP_PORT=8000

MYSQL_HOST=mysql
MYSQL_PORT=3306
MYSQL_DATABASE=vigilay
MYSQL_USER=vigilay
MYSQL_PASSWORD=change_me
MYSQL_ROOT_PASSWORD=change_me_root

DATABASE_URL=mysql+asyncmy://vigilay:change_me@mysql:3306/vigilay

SESSION_SECRET=CHANGE_ME
CREDENTIAL_ENCRYPTION_KEY=CHANGE_ME_BASE64_32_BYTE_KEY

SESSION_COOKIE_NAME=vigilay_session
SESSION_COOKIE_SECURE=false
SESSION_COOKIE_SAMESITE=lax

CORS_ALLOWED_ORIGINS=http://localhost:3000

LOG_LEVEL=INFO
```

Media:

```dotenv
MEDIAMTX_HOST=mediamtx
MEDIAMTX_RTSP_PORT=8554
MEDIAMTX_WEBRTC_PORT=8889
MEDIAMTX_HLS_PORT=8888

MEDIA_SESSION_TTL_SECONDS=60
MEDIA_ON_DEMAND=true
```

AI:

```dotenv
AI_ENABLED=true
YOLO_MODEL_PATH=/models/yolo11n.pt
YOLO_DEVICE=cpu
YOLO_CONFIDENCE=0.50
AI_PROCESSING_FPS=5

FACE_RECOGNITION_ENABLED=true
FACE_MATCH_THRESHOLD=0.60
```

Bunny:

```dotenv
BUNNY_ENABLED=false
BUNNY_API_KEY=
BUNNY_STORAGE_ZONE=
BUNNY_STORAGE_HOST=
BUNNY_STORAGE_PASSWORD=
BUNNY_CDN_BASE_URL=
```

Imou:

```dotenv
IMOU_ENABLED=false
IMOU_APP_ID=
IMOU_APP_SECRET=
IMOU_OPENAPI_BASE_URL=
```

EZVIZ:

```dotenv
EZVIZ_ENABLED=false
EZVIZ_APP_KEY=
EZVIZ_APP_SECRET=
EZVIZ_OPENAPI_BASE_URL=
```

Email:

```dotenv
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_TLS=true
```

Webhook:

```dotenv
WEBHOOK_SIGNING_SECRET=
```

Edge Agent example:

```dotenv
VIGILAY_CONTROL_PLANE_URL=https://api.example.com
VIGILAY_AGENT_NAME=
VIGILAY_AGENT_ID=
VIGILAY_PROVISION_TOKEN=

EDGE_DATA_DIR=/var/lib/vigilay
EDGE_LOG_LEVEL=INFO

ONVIF_DISCOVERY_ENABLED=true
RTSP_PROBE_ENABLED=true

AI_EXECUTION_ENABLED=true
YOLO_MODEL_PATH=/models/yolo11n.pt
YOLO_DEVICE=cpu

LOCAL_EVENT_BUFFER_ENABLED=true
LOCAL_EVENT_BUFFER_MAX_MB=512
```

Frontend:

```dotenv
PUBLIC_APP_NAME=Vigilay
PUBLIC_API_URL=http://localhost:8000
PUBLIC_DEFAULT_LOCALE=es-PE
```

Also document which variables belong in:

GitHub Secrets

GitHub Variables

Bunny environment variables

local `.env`

---

# 40. CAMERA CREDENTIAL SECURITY

Camera credentials are extremely sensitive.

Never store them as plain text.

Use application-level authenticated encryption.

Prefer AES-256-GCM or another industry-standard authenticated encryption construction.

Encryption master key comes from environment/secrets manager.

Never log:

camera passwords

complete RTSP URLs containing credentials

vendor AppSecrets

access tokens

refresh tokens

Edge Agent private keys

Redact sensitive values.

---

# 41. API

Create versioned API:

```text
/api/v1/auth/*
/api/v1/me

/api/v1/tenants
/api/v1/sites
/api/v1/users
/api/v1/roles

/api/v1/cameras
/api/v1/cameras/{id}
/api/v1/cameras/{id}/test
/api/v1/cameras/{id}/probe
/api/v1/cameras/{id}/capabilities
/api/v1/cameras/{id}/settings
/api/v1/cameras/{id}/commands
/api/v1/cameras/{id}/snapshot
/api/v1/cameras/{id}/ptz
/api/v1/cameras/{id}/streams
/api/v1/cameras/{id}/live-session
/api/v1/cameras/{id}/health

/api/v1/camera-profiles

/api/v1/edge-agents
/api/v1/edge-agents/{id}

/api/v1/events

/api/v1/known-people

/api/v1/ai-profiles

/api/v1/notification-rules

/api/v1/reports

/api/v1/audit

/api/v1/system/health
```

Automatically generate OpenAPI documentation.

---

# 42. REAL-TIME COMMUNICATION

Use WebSockets or Server-Sent Events as appropriate for:

camera online/offline changes

Edge Agent state

AI person counts

new events

notifications

device-command progress

configuration synchronization

---

# 43. DEVICE COMMAND QUEUE

Remote camera settings must use a reliable command system.

Example:

Super Admin clicks:

"Activar visión nocturna"

Backend:

1. authorizes user
2. validates camera capability
3. stores command
4. publishes command
5. Edge Agent receives command
6. Agent calls appropriate adapter
7. Agent obtains result
8. Agent reports result
9. backend updates reported state
10. UI receives realtime result

Do not block HTTP requests for long-running camera operations.

---

# 44. AUDIT

Audit important actions.

Examples:

LOGIN

LOGIN_FAILED

TENANT_CREATED

USER_CREATED

USER_DISABLED

CAMERA_CREATED

CAMERA_ASSIGNED

CAMERA_CREDENTIAL_UPDATED

CAMERA_SETTING_CHANGED

CAMERA_RESTARTED

PTZ_COMMAND

CONFIG_PROFILE_APPLIED

EDGE_AGENT_REGISTERED

EDGE_AGENT_REVOKED

AI_CONFIGURATION_CHANGED

KNOWN_PERSON_CREATED

KNOWN_PERSON_DELETED

NOTIFICATION_CHANGED

Do not include secrets in audit metadata.

---

# 45. SECURITY TESTING

Explicitly test:

SQL injection

XSS

CSRF

IDOR

tenant isolation

authentication bypass

role escalation

camera permission bypass

credential leakage

path traversal

unsafe uploads

rate-limit bypass

webhook spoofing

session fixation

Cross-tenant tests are mandatory.

Example:

User from Tenant A requests:

```text
GET /api/v1/cameras/<TENANT_B_CAMERA>
```

Expected:

403 or 404.

Never return Tenant B camera metadata.

---

# 46. RATE LIMITS

Rate-limit:

login

password reset

camera connection tests

network scans

snapshots

PTZ commands

vendor API calls

configuration writes

Use manufacturer API quotas responsibly.

---

# 47. CAMERA HEALTH

Track:

online state

last seen

last successful snapshot

last successful stream frame

RTSP connectivity

ONVIF connectivity

vendor API connectivity

Edge Agent connectivity

AI health

latency

reconnections

authentication failures

Create offline/online transition events.

---

# 48. SYSTEM HEALTH

Create health endpoints for:

API

MySQL

MySQL coordination tables

workers

media gateway

storage provider

Edge Agent fleet

AI service

External vendor integrations

---

# 49. LOGGING

Use structured logs.

Fields where appropriate:

timestamp

service

level

request_id

tenant_id

site_id

camera_id

edge_agent_id

event_type

Do not log secrets.

---

# 50. UI LANGUAGE

All user-facing application text must be Spanish.

Target users are initially in Peru.

Locale:

es-PE.

Do not translate code identifiers unnecessarily.

---

# 51. VIGILAY BRANDING

The application should visibly be branded:

Vigilay

Create a professional surveillance/control-center interface.

Style:

modern

clean

technical

enterprise

clear status indicators

responsive

Do not copy EZVIZ, Imou or V380 UI.

Vigilay needs its own identity.

---

# 52. PAGES

Public:

```text
/login
/forgot-password
/reset-password
```

Authenticated:

```text
/dashboard
/cameras
/cameras/[id]
/events
/notifications
/reports
/known-people
/profile
```

Admin:

```text
/admin/customers
/admin/customers/[id]
/admin/sites
/admin/users
/admin/cameras
/admin/camera-profiles
/admin/edge-agents
/admin/integrations
/admin/ai
/admin/notifications
/admin/audit
/admin/system
```

---

# 53. CAMERA DETAIL PAGE

Tabs:

EN VIVO

EVENTOS

CONFIGURACIÓN

IA

NOTIFICACIONES

SALUD

INFORMACIÓN

AUDITORÍA

Configuration tab should dynamically adapt to device capabilities.

---

# 54. SUPER ADMIN INTEGRATIONS PAGE

Create:

Vigilay → Administración → Integraciones

Providers:

Imou

EZVIZ

V380

ONVIF

Bunny.net

Email

Webhooks

Future providers

Show:

Enabled

Configured

Connection status

Last test

Last synchronization

"Probar conexión"

---

# 55. DATA MIGRATION

Inspect existing:

```text
reportes/conteo_personas.csv
reportes/visitas.csv
visitas/
rostros_conocidos/
```

Create optional import command.

Example:

```bash
vigilay migrate-legacy-data
```

Do not delete originals.

---

# 56. BACKUPS

Create documented backup strategy.

MySQL backup.

Media metadata.

Configuration.

Known-person metadata.

Encryption-key handling.

Do not store backups only on the same machine as the primary database.

---

# 57. TESTING

Backend:

unit tests

integration tests

authorization tests

database tests

adapter tests

Edge Agent tests

camera simulator tests

Frontend:

component tests

critical-flow tests

E2E tests

Create simulated cameras/adapters so CI can test without physical cameras.

---

# 58. CAMERA SIMULATOR

Create a development camera simulator.

It should simulate:

online camera

offline camera

RTSP availability

PTZ capability

settings

configuration updates

person events

motion events

This allows developers and CI to test Vigilay without hardware.

---

# 59. HARDWARE INTEGRATION TEST MODE

When real cameras are available, allow developers to provide credentials through local environment variables.

Never commit hardware credentials.

Create:

```text
RUN_HARDWARE_TESTS=false
```

Hardware tests run only when explicitly enabled.

---

# 60. DOCUMENTATION

Create:

```text
README.md

docs/
  ARCHITECTURE.md
  DATABASE.md
  AUTHENTICATION.md
  SECURITY.md
  EDGE_AGENT.md
  MEDIA_PIPELINE.md
  AI_PIPELINE.md
  CAMERA_ADAPTERS.md
  CAMERA_COMPATIBILITY.md
  IMOU_INTEGRATION.md
  EZVIZ_INTEGRATION.md
  V380_INTEGRATION.md
  BUNNY_DEPLOYMENT.md
  GHCR.md
  ENVIRONMENT_VARIABLES.md
  DEPLOYMENT.md
  BACKUPS.md
  OPERATIONS.md
```

---

# 61. ARCHITECTURE DIAGRAM

Document architecture using Mermaid.

At minimum show:

```text
Browser
  ↓
Vigilay Web
  ↓
Vigilay API
  ↓
MySQL
  ↓
Command/Event System
  ↓
Edge Agent
  ↓
ONVIF / RTSP / Vendor Adapter
  ↓
Camera
```

And media separately:

```text
Camera
 ↓
Edge Agent
 ↓
Media Gateway
 ↓
WebRTC
 ↓
Browser
```

---

# 62. GITHUB

Repository should be ready for GitHub.

Create:

`.gitignore`

GitHub Actions

Dependabot or equivalent where appropriate

PR checks

GHCR publishing

Security scanning

No secrets committed.

---

# 63. BUNNY MAGIC CONTAINERS CI/CD

Prepare deployment so GitHub Actions can:

1. build image
2. test image
3. push to GHCR
4. trigger Bunny Magic Containers rolling update

Use SHA-based immutable tags.

Example concept:

```text
ghcr.io/org/vigilay-api:<git-sha>
```

Do not rely only on `latest`.

---

# 64. INFRASTRUCTURE AS CODE

Where officially supported, prepare Terraform for Bunny infrastructure.

Do not execute destructive production Terraform automatically.

Provide:

plan

documentation

variables

example `.tfvars`

Never commit real API keys.

---

# 65. IMPLEMENTATION PHASES

PHASE 0

Repository analysis.

Create:

`docs/CURRENT_STATE.md`

`docs/ARCHITECTURE.md`

`docs/IMPLEMENTATION_PLAN.md`

Then continue automatically.

Do not stop and ask me whether to continue unless a true external credential or hardware dependency blocks progress.

---

PHASE 1

Monorepo foundation.

MySQL.

Migrations.

Authentication.

RBAC.

Tenants.

Customers.

Sites.

Users.

Super Admin.

Audit.

---

PHASE 2

Camera domain.

Camera adapters.

ONVIF.

RTSP.

Camera permissions.

Capability system.

Settings model.

Camera simulator.

---

PHASE 3

Edge Agent.

Provisioning.

Heartbeat.

Command queue.

Camera discovery.

Remote settings.

---

PHASE 4

Media layer.

Live streaming.

WebRTC.

Camera grid.

On-demand streams.

---

PHASE 5

Migrate existing YOLO.

Person detection.

Events.

AI profiles.

Snapshots.

---

PHASE 6

Notifications.

In-app.

Email.

Webhook.

---

PHASE 7

Facial recognition.

Known people.

Face samples.

Face events.

Tenant isolation.

---

PHASE 8

Official Imou integration.

Implement and test documented capabilities.

---

PHASE 9

Official EZVIZ integration.

Implement and test documented capabilities.

---

PHASE 10

V380 investigation/integration.

Probe real supported protocols.

Document compatibility by tested device/firmware.

---

PHASE 11

Reports.

Storage.

Bunny Storage integration.

---

PHASE 12

GitHub Actions.

GHCR.

Bunny Magic Containers deployment configuration.

Production documentation.

---

PHASE 13

Security hardening.

Cross-tenant penetration tests.

Performance tests.

Failure tests.

---

# 66. DEFINITION OF MVP DONE

MVP is NOT complete until the following flow works:

Open Vigilay.

Login as Super Admin.

Create Customer A.

Create Site A.

Create Customer A administrator.

Create an Edge Agent.

Provision the Edge Agent.

Agent appears online.

Discover a camera or manually add an RTSP/ONVIF camera.

Test camera credentials.

Detect camera capabilities.

Save camera.

Assign camera to Customer A.

Open live camera.

See WebRTC video.

Enable YOLO.

See person count.

Generate event.

Receive in-app notification.

Open event.

See snapshot.

Open camera configuration.

Read supported settings.

Change one supported camera setting.

Receive command result.

Read setting again.

Verify desired and reported values match.

Login as Customer A.

See Customer A camera.

Login as Customer B.

Verify Customer B cannot discover or access Customer A camera, stream, event or API object.

Restart the central stack.

Verify users, cameras, events and configuration remain stored.

Run tests.

All critical tests pass.

---

# 67. DEFINITION OF CAMERA MANAGEMENT DONE

A camera integration cannot be called VERIFIED until Vigilay has actually tested against either:

a real compatible device

an official manufacturer test environment

or an authoritative protocol implementation.

Record:

manufacturer

model

firmware

integration

capabilities

test date

test result

Never label an entire manufacturer supported based on one camera model.

---

# 68. IMPORTANT RULE FOR ASTRA

Do not just write plausible code.

RUN IT.

TEST IT.

FIX ERRORS.

Run migrations.

Run backend tests.

Run frontend tests.

Build containers.

Verify services start.

Verify database connectivity.

Verify authorization.

Verify tenant isolation.

Verify command processing.

Verify simulated camera integration.

Do not mark something implemented because files exist.

---

# 69. DO NOT CREATE A MOCKUP-ONLY PRODUCT

This project must contain real backend logic.

Buttons must connect to real endpoints.

Endpoints must connect to real services.

Migrations must actually run.

Authentication must actually work.

RBAC must actually be enforced.

Camera settings must go through adapters.

The camera simulator can be used for automated testing, but production adapters must remain separate.

---

# 70. DO NOT ASK ME TO CHOOSE TECHNOLOGIES UNLESS ABSOLUTELY NECESSARY

You are responsible for architectural decisions.

If a different language, library, message queue, media server, ORM, database driver or framework provides a materially better solution:

evaluate it,

document the decision,

use it.

Do not choose a weaker architecture merely because the old prototype uses Flask.

Do reuse existing computer-vision logic where appropriate.

---

# 71. CURRENT PRIORITY

The highest-priority capability is:

CENTRALIZED MANAGEMENT OF CUSTOMERS + USERS + CAMERAS + CAMERA CONFIGURATION + LIVE VIEW + AI + NOTIFICATIONS.

Do not spend the first implementation phases on decorative UI.

Functionality first.

Then polish the interface.

---

# 72. START NOW

Begin by:

1. inspecting the entire repository;
2. reading `DESCRIPCION_PROYECTO.md`;
3. producing `docs/CURRENT_STATE.md`;
4. producing `docs/ARCHITECTURE.md`;
5. producing `docs/IMPLEMENTATION_PLAN.md`;
6. designing the MySQL migrations;
7. creating the monorepo foundation;
8. creating `.env.example`;
9. creating the development Docker Compose environment;
10. implementing Phase 1.

Continue implementation rather than stopping after the documentation.

The project name everywhere is:

Vigilay

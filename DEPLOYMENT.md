# DevNet deployment: agent-mandate DAR

Prepared checklist. Nothing here has been executed against DevNet.

## RESOLVED by the integration pass

- **Exact Token Standard V1 DAR identities** - the three official DevNet
  interface DARs are saved in `daml-starter/token-standard/official/`, and
  their package IDs are recorded below.
- **Source-rebuild package mismatch** - both packages now compile against
  those official DARs, not our source rebuilds. The old rebuilt IDs
  (`a2b71e27…` metadata, `4787754c…` holding, `a1d7f008…` transfer-instr.)
  are no longer referenced by the build; the upstream source is kept under
  `token-standard/splice-api-token-*-v1/` as reference only.
- **Clean production DAR packaging** - the deployable
  `agent-mandate-0.1.0.dar` contains only `Mandate` plus the three official
  interface packages: no `daml-script`, no tests, no mock/malicious
  factories, no Iou. Verified by `inspect-dar` (see below).

## The artefact

Build everything from `daml-starter/`:

```powershell
daml build --all
```

| DAR | Purpose | Deploy? |
|---|---|---|
| `daml-starter/mandate/.daml/dist/agent-mandate-0.1.0.dar` | Mandate + the three official Token Standard interface packages | **YES - this one only** |
| `daml-starter/.daml/dist/daml-starter-0.0.1.dar` | tests, mock registry, malicious mock factories, daml-script | **NEVER** |

Package identities in the deployable DAR (from
`daml damlc inspect-dar mandate/.daml/dist/agent-mandate-0.1.0.dar`):

| Package | Version | Package-id |
|---|---|---|
| `agent-mandate` | 0.1.0 | `47ead15bf3b4d49bdee259a473fa8216e97226af4e752869f57c4f5f2c0cdf09` |
| `splice-api-token-metadata-v1` | 1.0.0 | `4ded6b668cb3b64f7a88a30874cd41c75829f5e064b3fbbadf41ec7e8363354f` |
| `splice-api-token-holding-v1` | 1.0.0 | `718a0f77e505a8de22f188bd4c87fe74101274e9d4cb1bfac7d09aec7158d35b` |
| `splice-api-token-transfer-instruction-v1` | 1.0.0 | `55ba4deb0ad4662c4168b39859738a0e91388d252286480c7331b3f71a517281` |

SHA-256 of the official interface DAR files (`token-standard/official/`):

| File | SHA-256 |
|---|---|
| `splice-api-token-metadata-v1-1.0.0.dar` | `455eb160cb5abd4ae9918a6fbb9dad471f721adda39f0e5c76feef08d05637fc` |
| `splice-api-token-holding-v1-1.0.0.dar` | `ef75f8eb41a65810221784fdb78bb9dfac7cb22245aba14fa7cb7f69c34e0175` |
| `splice-api-token-transfer-instruction-v1-1.0.0.dar` | `e4c73aa7ae73fb2fc330b938ffb99f568792321640ba4b9472902aa8d742c994` |

Cantor8 runs several Amulet *implementation* versions on DevNet
simultaneously, so we deliberately depend on the stable Token Standard
*interfaces* above, not on any pinned Amulet implementation package ID. No
`splice-amulet` implementation DAR is bundled.

## G1 - confirm the interfaces are known to the participant (read-only)

The interface IDs are already the official ones, so this is a confirmation,
not a gate. From the already-authenticated PowerShell session:

```powershell
$tok = (Invoke-RestMethod -Method Post `
  -Uri "$env:C8_IDP/realms/master/protocol/openid-connect/token" `
  -ContentType "application/x-www-form-urlencoded" `
  -Body @{grant_type="client_credentials"; client_id=$env:C8_CLIENT_ID; client_secret=$env:C8_CLIENT_SECRET}).access_token
$H = @{Authorization = "Bearer $tok"}
$pkgs = (Invoke-RestMethod -Uri "$env:C8_BASE/v2/packages" -Headers $H).packageIds

# the three official interface ids should already be present:
"4ded6b668cb3b64f7a88a30874cd41c75829f5e064b3fbbadf41ec7e8363354f",
"718a0f77e505a8de22f188bd4c87fe74101274e9d4cb1bfac7d09aec7158d35b",
"55ba4deb0ad4662c4168b39859738a0e91388d252286480c7331b3f71a517281" |
  ForEach-Object { "$_  present=$($pkgs -contains $_)" }
```

All three present (expected) means only our own `agent-mandate` package is
new at upload time.

## G2 - upload (mutating; only after G1 confirms)

Upload = one Ledger API call. **Vetting is NOT a separate step here**: a DAR
uploaded through the Ledger API package service is vetted automatically on
the participant's connected synchronizers (Canton default
`vetAllPackages=true`). Separate vet/unvet operations exist only on the
participant Admin API (topology), which we do not have and should not need.

```powershell
Invoke-RestMethod -Method Post -Uri "$env:C8_BASE/v2/packages" -Headers $H `
  -ContentType "application/octet-stream" `
  -InFile "daml-starter\mandate\.daml\dist\agent-mandate-0.1.0.dar"

# verify it landed (read-only)
(Invoke-RestMethod -Uri "$env:C8_BASE/v2/packages" -Headers $H).packageIds `
  -contains "47ead15bf3b4d49bdee259a473fa8216e97226af4e752869f57c4f5f2c0cdf09"
```

The `agent-mandate` id `47ead15b…` is stable as long as `Mandate.daml` and
its (now official) interface dependencies are unchanged; a rebuild after any
change to those will produce a new id, so re-run `inspect-dar` if in doubt.
There is no un-upload from the Ledger API.

Alternative (gRPC, if the JSON route is blocked):
`daml ledger upload-dar --host api.validator.dev.digik.cantor8.tech --port 443 --access-token-file <file> mandate/.daml/dist/agent-mandate-0.1.0.dar`
- untested here; the JSON call is the primary path.

## G3 - parties, rights, smoke test (mutating, small)

```powershell
$env:C8_BASE / C8_IDP / C8_CLIENT_ID / C8_CLIENT_SECRET / C8_REGISTRY  # already set
python c8lab.py check                       # read-only sanity
python c8lab.py rights <actual-user-id>     # read-only: what the credential really holds
python c8lab.py party d1owner               # allocate (grants nothing)
python c8lab.py party d1agent
python c8lab.py grant <user> d1owner --read # CanReadAs(owner)
python c8lab.py grant <user> d1agent        # CanActAs(spender)
python c8lab.py check-agent <user> d1agent d1owner   # honest PASS/FAIL
# fund d1owner (ask the team to send Canton Coin), receiver needs preapproval
python c8lab.py preapproval <receiver>
# smoke test with a tiny cap:
python c8lab.py mandate-propose d1owner d1agent <receiver> 5
python c8lab.py mandate-accept <proposalCid> d1agent
python c8lab.py mandate-settle <mandateCid> d1owner d1agent <receiver> 1
```

Caveats already known: DevNet party allocation may need the external-party
flow instead of `POST /v2/parties` (README), and `check-agent` will FAIL on
the shared broad credential until organisers issue a per-service user -
that failure is the honest result, not a bug.

## Rights required per step

| Step | Right needed |
|---|---|
| G1 list packages | any authenticated user (read) |
| G2 upload DAR | **participant admin** on the Ledger API user |
| G3 allocate party / grant rights / create user | **participant admin** |
| G3 propose / accept / settle / read ACS | normal app rights (CanActAs / CanReadAs on the involved parties) |

Whether the shared hackathon credential carries participant-admin is
unknown until `rights <user>` / a G2 dry attempt says so; if it does not,
G2 and the G3 admin steps are organiser actions.

## Who runs what

Claude's process currently has no `C8_*` variables; the user's PowerShell
session is authenticated. Every command above is paste-ready for that
session. If the variables are exported into a shell Claude can use, the
same steps run through `c8lab.py` unchanged.

## Genuinely unresolved DevNet items

1. Which actual Ledger API user the shared Keycloak `hackathon` client maps
   to (needed before `rights <user>` / `check-agent` mean anything).
2. That user's real rights, and whether it has package-upload / participant-
   admin authority (decides whether we or an organiser runs G2 and the G3
   admin steps).
3. Whether Cantor8 can provide a least-privilege agent credential
   (CanActAs(spender) + CanReadAs(owner) only) so `check-agent` passes on
   DevNet rather than only on LocalNet.
4. Live party + preapproval setup (party allocation there may need the
   external-party flow, not `POST /v2/parties`), and Canton Coin funded to
   the owner party.
5. Live settlement proof: an actual on-DevNet `mandate-settle` against real
   Amulet, which `daml test` cannot stand in for.

The three Token Standard interface DARs are no longer on this list - they
are in `token-standard/official/` and their IDs are recorded above.

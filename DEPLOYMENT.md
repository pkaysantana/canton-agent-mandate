# DevNet deployment: agent-mandate DAR

Prepared checklist. Nothing here has been executed against DevNet. Gate G1
must pass before anything is uploaded.

## The artefact

Build everything from `daml-starter/`:

```powershell
daml build --all
```

| DAR | Purpose | Deploy? |
|---|---|---|
| `daml-starter/mandate/.daml/dist/agent-mandate-0.1.0.dar` | Mandate + the three Token Standard interface packages | **YES - this one only** |
| `daml-starter/.daml/dist/daml-starter-0.0.1.dar` | tests, mock registry, malicious mock factories, daml-script | **NEVER** |

Local package identities as of this commit (from
`daml damlc inspect-dar mandate/.daml/dist/agent-mandate-0.1.0.dar`):

| Package | Version | Local package-id |
|---|---|---|
| `agent-mandate` | 0.1.0 | `c9b0c9967704bbb7e70bad5eefd557a689cdf8d13ad66ecdb4b02290c475412f` |
| `splice-api-token-metadata-v1` | 1.0.0 | `a2b71e271f87b8d5282607f079262355eb2e42e20857613a47fce290fc3b3cde` |
| `splice-api-token-holding-v1` | 1.0.0 | `4787754c493877d34db18aae4889cb96e07f1979ca758f5d15017606ece9d0cd` |
| `splice-api-token-transfer-instruction-v1` | 1.0.0 | `a1d7f008c9e8b4400e829fabc5fe1d1b6d201b9d514d37f4e723da7e51bd7817` |

The three `splice-api-token-*-v1` packages are VENDORED SOURCE REBUILDS
(from the Splice repo at tag 0.6.8, compiled with SDK 3.4.10 instead of
upstream's 3.4.11). Their package-ids almost certainly differ from the ones
deployed on DevNet, and Canton rejects a second package with the same
(name, version) but a different package-id. **That is the whole risk; G1
resolves it.**

## G1 - verify interface package identities (read-only, run first)

From the already-authenticated PowerShell session:

```powershell
# token (already working in that session; shown for completeness)
$tok = (Invoke-RestMethod -Method Post `
  -Uri "$env:C8_IDP/realms/master/protocol/openid-connect/token" `
  -ContentType "application/x-www-form-urlencoded" `
  -Body @{grant_type="client_credentials"; client_id=$env:C8_CLIENT_ID; client_secret=$env:C8_CLIENT_SECRET}).access_token
$H = @{Authorization = "Bearer $tok"}

# every package-id the participant knows (read-only)
$pkgs = (Invoke-RestMethod -Uri "$env:C8_BASE/v2/packages" -Headers $H).packageIds

# are OUR three vendored ids already there?
"a2b71e271f87b8d5282607f079262355eb2e42e20857613a47fce290fc3b3cde",
"4787754c493877d34db18aae4889cb96e07f1979ca758f5d15017606ece9d0cd",
"a1d7f008c9e8b4400e829fabc5fe1d1b6d201b9d514d37f4e723da7e51bd7817" |
  ForEach-Object { "$_  present=$($pkgs -contains $_)" }
```

Outcomes:

- **All three present** -> our rebuild matches DevNet byte-for-byte; upload
  of `agent-mandate-0.1.0.dar` is safe as-is. (Unlikely but possible.)
- **Any absent** -> we need the exact deployed DARs from Davide (ask for
  the three `splice-api-token-*-v1` DAR files, or the package-ids so we can
  fetch/verify). Then:

  ```powershell
  # drop the official DARs into daml-starter/token-standard/official/
  # point BOTH daml.yaml data-dependencies at them (mandate/ and root),
  # rebuild and re-verify:
  daml build --all
  daml test                       # all 19 scripts must stay green
  daml damlc inspect-dar mandate/.daml/dist/agent-mandate-0.1.0.dar
  # the three splice-api ids in the inspect output MUST now equal DevNet's
  ```

Optional cross-check if the JSON API version supports it (read-only): the
preferred-packages endpoint resolves a package NAME to the id the
participant would actually use:

```powershell
Invoke-RestMethod -Method Post -Uri "$env:C8_BASE/v2/interactive-submission/preferred-packages" `
  -Headers $H -ContentType "application/json" -Body (@{
    packageVettingRequirements = @(
      @{ packageName = "splice-api-token-transfer-instruction-v1"; parties = @() })
  } | ConvertTo-Json -Depth 5)
```

## G2 - upload (mutating; only after G1 passes)

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
  -contains "<agent-mandate package-id from inspect-dar after G1>"
```

Note: if G1 forced a rebuild against official DARs, the `agent-mandate`
package-id CHANGES from the table above - always take it from the final
`inspect-dar` output. There is no un-upload from the Ledger API; that is
why G1 comes first.

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

## Still needed from Davide

1. The three deployed `splice-api-token-*-v1` DAR files (or package-ids) -
   unless G1 shows ours already match.
2. Confirmation the hackathon credential may upload DARs (or an organiser
   runs G2).
3. A per-service user for the agent (CanActAs(spender) + CanReadAs(owner)
   only) so `check-agent` can pass on DevNet.
4. `C8_REGISTRY` base URL for transfers, and Canton Coin sent to the owner
   party.

# Agent Mandate — demo video narration

For `Agent_Mandate_Cantor8_Demo.mp4` (2:28, silent). Record separately
and overlay. Timestamps mark where each visual section begins; speak
each block within its window. Total spoken script ≈ 2:20.

| Time | On screen | Say |
|---|---|---|
| 0:00 | Title — Agent Mandate | AI agents are increasingly able to initiate financial actions. But the model itself shouldn't decide how much authority it has. |
| 0:07 | Hero line | Agent Mandate separates those two things. |
| 0:12 | Console overview | This is the authority console. The owner has funds available — and the agent has a separate Daml Mandate. |
| 0:24 | Authority panel zoom | Four point nine nine seven Canton Coin in funds, but only zero point zero zero seven of delegated authority. Recipient permissions, a cumulative cap, expiry and revocation — all defined in the Mandate. |
| 0:32 | Pipeline — "AI proposes intent. Daml owns the policy." | The model's job is narrow: turn a request into recipient, amount and reason. |
| 0:40 | Pipeline — "Python deliberately does not enforce the cap." | Python deliberately doesn't enforce the financial policy. That boundary lives in Daml. |
| 0:48 | Accepted request, full console | An approved request — pay the pharmacy zero point zero zero one Canton Coin — is accepted. |
| 0:58 | Settlement close-up + mandate advance | The payment settles, and the consumed Mandate is replaced with a successor carrying the updated cumulative spend: spent moves to zero point zero zero four, remaining to zero point zero zero six. |
| 1:14 | Over-cap request, full console | Now I explicitly tell the agent to ignore the spending limit and request zero point zero one one Canton Coin. |
| 1:26 | Rejection close-up (climax) | The recipient is approved. The wallet can afford it. The model proposes it and the application forwards it. But the agent doesn't have that authority. Daml rejects the transaction: charge would exceed the cap. Zero value moves. |
| 1:37 | The four checks | Three checks pass. The fourth — delegated authority — fails. The decision is deterministic, and it is not the model's to make. |
| 1:50 | Verified DevNet evidence card | We verified the same authority boundary on Cantor8 DevNet using real Canton Coin. At the isolation test the wallet held four point nine nine seven, but the Mandate had only zero point zero zero seven remaining. A zero point zero zero eight request reached Mandate dot ChargeAndSettle — and Daml rejected it. Zero value moved. |
| 2:09 | Thesis | Having access to money is not the same as having authority to spend it. |
| 2:17 | Closing | Agent Mandate: AI intent, deterministic financial authority. |

Notes:

- The console footage is the deterministic fixture replay, labelled
  DEMO · VERIFIED ON DEVNET on screen; the DevNet evidence card at 1:50
  is the separately verified real-coin result. Don't call the replay
  live.
- The 0.008 CC isolation test used deterministic manual intent — don't
  describe it as LLM-generated.

## Rebuild the video

```
cd video
npm install
node serve.mjs 8451            # terminal 1
# terminal 2:
#   capture the three UI states (see capture.html header for flows)
"msedge" --headless=new --window-size=1920,1080 --hide-scrollbars ^
  --virtual-time-budget=22000 --screenshot=captures/rejected.png ^
  "http://localhost:8451/video/capture.html?flow=rejected"
powershell -File crop.ps1      # zoom crops from the 2x captures
node build_slides.mjs          # demo_timeline.pptx + timeline.json
powershell -File make_video.ps1  # -> Agent_Mandate_Cantor8_Demo.mp4
```

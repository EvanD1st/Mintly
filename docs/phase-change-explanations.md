# Phase-change explanations

Phase tracking still stops an unsigned mint when its pinned price, mint method or wallet limit changes. Only the explanation and diagnostics change. The comparison, authorization, signing, retry and funding rules remain unchanged.

New price messages show the old and observed prices per NFT in the correct native currency. A zero price is shown as free; a missing price is unverified, never free. A free-only approval that encounters a positive price explicitly says Free-only mint stopped. Method and wallet-limit changes name the changed values. Integer formatting preserves one wei without floats.

The shared lifecycle recognizes these generated notes and known legacy phase-change notes as terms_changed, with a Mint terms changed headline. Legacy generic notes are clarified without inventing historical prices. Today, Mint Plans and Activity already use this read model, so current builds6/7 receive the explanation on refresh with no new mobile code or OTA.

Schedule-check stops now record an allowlisted terms_changed diagnostic in the existing diagnostics table. Recording failures cannot prevent the original protective stop or reservation settlement. Reliability reporting considers schedule diagnostics as well as preparation diagnostics, so pre-preparation phase changes do not appear as Unknown.

Binzo's historical note correction is a separately audited, guarded data repair using verified OpenSea/current chain state and PublicDropUpdated events. It changes only the explanation on its already-failed unsigned task; no historical attempt is invented, no mint is rearmed, and no permission or debit is changed.

Tests cover free-to-paid changes on ETH/APE/HYPE, smaller exact units, paid-to-free changes that still require review, unknown prices, method/limit changes, safe legacy classification and a real local EVM phase update. Integration checks confirm unchanged consent, zero signing/broadcast, released reservation, consistent Queue/Activity messages, correct reliability classification and diagnostic-failure isolation.

# Daily Today notifications

The notification service polls saved current-WAT-day lists every 15 seconds. Only supported Today collections with usable links count. Historic, future-dated and unsupported lists do not send alerts. Daily notices are unique per WAT day, account and registered device; repeated source polling, reprocessing and restarts do not reseed them. Devices registered or opted in later can receive the current day's list.

Delivery uses the existing Firebase-enabled automatic-notifications service. Discovery never receives Firebase credentials, and neither queueing nor sending uses OpenSea, the signer or the execution lock. Consent, active account, token ownership and current list availability are checked before sending. Notices retry up to five times with 60/120/240/480-second delays, expire at WAT midnight and recover abandoned 90-second leases. A stable Android notification tag limits duplicates after an uncertain delivery. FCM acceptance is not proof of phone presentation.

Users need Android notification permission and Account settings -> New drop notifications enabled. Existing APK 1.1.4+7 supports these alerts; no APK or OTA is required. Additive migration 027_daily_list_notices creates the durable outbox. Discovery/manual import stop direct sends to avoid duplicate or historical-list alerts.

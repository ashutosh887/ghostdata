-- Captured at: 2026-10-22T08:00:00Z
-- Database topology: primary
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE snapshot_scope (origin_system TEXT PRIMARY KEY, captured_at TEXT NOT NULL);
CREATE TABLE customer_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, full_name TEXT, email TEXT, phone TEXT, email_hash TEXT, account_status TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO snapshot_scope VALUES ('account_service', '2026-10-22T08:00:00Z');
INSERT INTO customer_profiles VALUES ('account_9201', 'user_201', 'Hannah Kowalski', 'hannah.kowalski@example.com', '+1 (212) 555-0150', 'd3650e32c2b9275679c408e25ae1d2af07f8db1f9ee864374be5905e7ee8e0ae', 'ACTIVE', '2026-10-22T00:10:00Z');
INSERT INTO customer_profiles VALUES ('account_9202', 'user_202', 'Samuel Adeyemi', 'samuel.adeyemi@example.net', '+1 (212) 555-0151', '2e55fe3c8312d6d9c89d2324d28def8053e2f29f966562e38b6666a866c08fe0', 'ACTIVE', '2026-10-22T01:11:00Z');
INSERT INTO customer_profiles VALUES ('account_9203', 'user_203', 'Isabel Quintero', 'isabel.quintero@example.org', '+1 (212) 555-0152', '76bf51d0044823c380e023540416974763f3ba92dc558151ac1569d40b87edb1', 'ACTIVE', '2026-10-22T02:12:00Z');
INSERT INTO customer_profiles VALUES ('account_9204', 'user_204', 'Erik Nyström', 'erik.nystrom@example.com', '+1 (212) 555-0153', '38dc13f77dc9fc3eddaf33d4b6a07546f6b5ca312595e4b8e33e80ff12b504dd', 'ACTIVE', '2026-10-22T03:13:00Z');
INSERT INTO customer_profiles VALUES ('account_9205', 'user_205', 'Mei Chen', 'mei.chen@example.net', '+1 (212) 555-0154', 'b149484630cb03312844c9b8fe42c06a0b882f1155ed26701d50aae1c3349438', 'ACTIVE', '2026-10-22T04:14:00Z');
INSERT INTO customer_profiles VALUES ('account_9206', 'user_206', 'Arjun Mehta', 'arjun.mehta@example.org', '+1 (212) 555-0155', '95f1a9ba4dccba81fedddc11d23b90a9fd86ada68eb04869863074279280326c', 'ACTIVE', '2026-10-22T05:15:00Z');
INSERT INTO customer_profiles VALUES ('account_9207', 'user_207', 'Zoe Whitaker', 'zoe.whitaker@example.com', '+1 (212) 555-0156', '5de180f543429e2639d4b133079bb4b11ac0b35ec60fbfb24f06039c1abfa797', 'ACTIVE', '2026-10-22T06:10:00Z');
INSERT INTO customer_profiles VALUES ('account_9208', 'user_208', 'Pedro Saraiva', 'pedro.saraiva@example.net', '+1 (212) 555-0157', '8f49a29132d48359b79a7c265cdc4201fb3fc64eabc955d43ab0e34b823f4638', 'ACTIVE', '2026-10-22T07:11:00Z');
INSERT INTO customer_profiles VALUES ('account_9209', 'user_209', 'Leila Haddad', 'leila.haddad@example.org', '+1 (212) 555-0158', '725b99a9aad331ebcd543ab54ecfa8de4fbf1756dcf30716d2541dcf899ca8f3', 'ACTIVE', '2026-10-22T00:12:00Z');
INSERT INTO customer_profiles VALUES ('account_9210', 'user_210', 'Victor Lambert', 'victor.lambert@example.com', '+1 (212) 555-0159', 'ab3ce8d8b13d69af258ae607c9b47a1a1f4356dd6d7c4c19ecfef28d027e643e', 'ACTIVE', '2026-10-22T01:13:00Z');
INSERT INTO customer_profiles VALUES ('account_9211', 'user_211', 'Ruth Abernathy', 'ruth.abernathy@example.net', '+1 (212) 555-0160', '4645fc13aaaf5a68fcf65e3f8c17d4872b68a4f3d7c62382eac5b37a94f9a1d7', 'ACTIVE', '2026-10-22T02:14:00Z');
INSERT INTO customer_profiles VALUES ('account_9212', 'user_212', 'Kenji Watanabe', 'kenji.watanabe@example.org', '+1 (212) 555-0161', 'bd2578afcb815ccc0f2259b1daeb97b42691eb15c14bd68ae4b7583d76b18750', 'ACTIVE', '2026-10-22T03:15:00Z');
INSERT INTO customer_profiles VALUES ('account_9213', 'user_213', 'Olga Ivanova', 'olga.ivanova@example.com', '+1 (212) 555-0162', '3deb9037a1e8c6f5ba33ba9b0411ec4700137d475dfca77819685020c14d590a', 'ACTIVE', '2026-10-22T04:10:00Z');
INSERT INTO customer_profiles VALUES ('account_9214', 'user_214', 'Tariq Aziz', 'tariq.aziz@example.net', '+1 (212) 555-0163', 'f11d6f05752ce2a78869cb22e744ff8220edc6b8e82741a1aece053e8ac847b9', 'ACTIVE', '2026-10-22T05:11:00Z');
INSERT INTO customer_profiles VALUES ('account_9221', 'user_221', 'Maya Lindqvist', 'mlindqvist.design@example.org', '+1 (312) 555-0181', '4820009c019270eb5520d43061666615d21a4ea6063dad3e0b93a8db1c9adb73', 'ACTIVE', '2026-10-22T06:12:00Z');
INSERT INTO customer_profiles VALUES ('account_9222', 'user_222', 'Jonas Berg', 'jonas.berg.cph@example.net', '+1 (312) 555-0182', 'bfdea5d44f3aa566edcff58840e3f212759c8c17e69a7f74a5251580378c04fa', 'ACTIVE', '2026-10-22T07:13:00Z');
INSERT INTO customer_profiles VALUES ('account_9223', 'user_223', 'Nadia Petrova', 'n.petrova.art@example.com', '+1 (312) 555-0183', '5a8fed71d628c31d962ceb7279d981c5f4fc8e065566a9ced83138f1985c140c', 'ACTIVE', '2026-10-22T00:14:00Z');
INSERT INTO customer_profiles VALUES ('account_8008', 'user_108', 'Lena Fischer', 'lena.fischer@example.net', '+1 (415) 555-0108', 'c9a9041375fc64586353878ae08176cd5947dfab9e7a7a444559a7a364808774', 'ACTIVE', '2026-10-22T01:15:00Z');
INSERT INTO customer_profiles VALUES ('account_8026', 'user_126', 'Ben Archer', 'ben.archer@example.com', '+1 (415) 555-0126', '969f8cb4c6c42c1a4a507c43277dca10f773209cbdf2c82d611b627259cffa12', 'ACTIVE', '2026-10-22T02:10:00Z');
CREATE INDEX idx_customer_profiles_email ON customer_profiles(email);
COMMIT;

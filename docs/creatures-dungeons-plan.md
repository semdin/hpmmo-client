# Yaratıklar, Bosslar ve Zindanlar — Uygulama Planı

Durum: **ONAYLANDI** (2026-10-16, varsayılan kararlarla). M0 başladı.

Kapsam (istek sırası):

0. Mob sistemi: mantık, haritada nerede/hangi seviyede çıkacakları
1. Yeni mob + bosslar: **Ruh Emiciler (Dementor)** ve **Troller**
2. Hogwarts 3. katından girilen zindan — **Kabarık (üç başlı köpek)**, MMO zindan mantığı
3. Detaylı **ejderha zindanı**

Tüm 2D tasarım/konsept ve 3D modeller **fal.ai** üzerinden; her fal işinden önce
maliyet tahmini gösterilir (mevcut kural).

---

## 0. Mevcut durum (neyin üzerine kuruyoruz)

Sıfırdan değil — sağlam bir temel var:

| Var olan | Nerede | Ne yapıyor |
|---|---|---|
| `mob_base.gd` (1088 satır) | `client/scripts/entities/mobs/` | AI: idle/wander/chase/attack/return/dead, reactive aggro, pack assist, leash, attack slot halkası, ayrışma, telegraph'lı boss saldırıları (anticipation → release → recovery), puppet replikasyonu |
| `encounter_director.gd` | `client/scripts/world/` | Pack şablonları (3'lü, 5'li, solo boss, 2 eskortlu boss), güvenli yerleşim doğrulaması, respawn, kamp yapan oyuncu varken ertelenen respawn |
| `spawn_tables.json` | `addons/hpmmo_sim/data/` | 9 bölge, 8 encounter, `pack_tuning` (seviyeden HP/atak/exp), `boss_overrides`, `boss_patterns` (spider, wizard) |
| `loot_tables.json` | aynı | Tek bir `mob` tablosu (tüm moblar aynı drop), boss tablosu, respawn süreleri |
| Mob türleri | — | `inferi`, `acromantula`, `darksnatcher` + 2 boss (Matriarch, Commander) |
| Haritalar | `maps.json` | `grounds` ve `castle_interior` (y-bandı ile ayrılmış), portallar |

**Eksikler (bu plan bunları kapatıyor):**

- Mob türü verisi koda dağınık (scene + export değişkenleri); merkezi bir **mob kataloğu** yok.
- Tüm moblar aynı loot tablosunu kullanıyor; tür/seviye bazlı drop yok.
- Bölgelerin **seviye aralığı** yok; oyuncu nereye gideceğini bilmiyor.
- Boss mekanikleri sadece 2 tür (yönlü + alan). Faz, çağırma, hücum, nefes taraması, zemin efekti yok.
- **Parti sistemi yok.**
- **Instance (kopya harita) yok** — zindan için şart.
- Sadece 7 büyü var (Patronus, Lumos yok) — dementor tasarımını etkiliyor (bkz. Kararlar).

---

## Faz M0 — Mob Sistemi v2 (veri + dünya yerleşimi)

> **Durum (2026-10-16): M0 çekirdeği bitti, commit edilmedi.** Teslim edilenler: `data/mobs.json` kataloğu
> (3 tür), element bazlı `resist` (spells.json `element`), bölge seviye bantları + HUD "Hunting grounds · Lv a-b",
> %3 elit (×3 HP, ×1.5 atak, ×3 exp, ek loot), tür/elit loot tabloları, Metin2 seviye farkı (exp + drop),
> **protokol v14** `sim_mob_info` (online istemciler mob adı/seviye/elit görür).
> Testler: client regresyon 144/0, multiplayer 50/0, encounters 102/0.
> **M1'e taşınanlar** (yaratıkla birlikte test edilebilir oldukları için): yeni yetenek türleri (M0.4),
> tehdit tablosu, devriye, gece/gündüz, zamanlı world boss + duyuru, stun direnci.

### M0.1 Mob kataloğu — `addons/hpmmo_sim/data/mobs.json` (yeni, sunucu sahibi)

Her tür tek bir kayıtta:

```jsonc
"troll_forest": {
  "display": "Orman Trolü",
  "family": "troll",              // troll | dementor | beast | undead | dark_wizard | dragon | construct | plant
  "scene": "res://scenes/entities/mobs/mob_troll.tscn",
  "variant": "forest",             // aynı rig, farklı doku/ölçek
  "anim_set": "troll", "voice_set": "troll",
  "role": "brute",                 // brute | skirmisher | caster | swarm | elite
  "stats": { "hp_mult": 1.8, "atk_mult": 1.3, "speed": 4.2, "attack_range": 3.2, "attack_cooldown": 2.2 },
  "resist": { "fire": 0.0, "stun": 0.5, "knockback": 0.8 },   // weak_to_fire'ın genelleşmiş hali
  "abilities": ["club_slam", "stomp"],
  "aggro_mode": "reactive",
  "loot_table": "troll",
  "night_only": false
}
```

- `weak_to_fire` bool'u → `resist` sözlüğüne genişler (`fire`, `stun`, `knockback`, `dark`…, negatif = zayıflık). `HPRules.damage_after_resistances` buna göre güncellenir.
- Encounter'lar `mob` alanında bu id'leri kullanır; `mob_scenes` ve `boss_overrides` katalogla birleşir.
- `abilities` → yeni **yetenek kütüphanesi** (`boss_patterns` genelleşir, bkz. M0.4). Sıradan mobların da 1-2 özel saldırısı olur.

### M0.2 Bölge seviye haritası (Metin2 mantığı: kaledan uzaklaştıkça zorlaşır)

Mevcut arazi işaretlerine (layout.json `landmarks/features`) göre:

| Kademe | Seviye | Bölge (mevcut işaret) | Yaratıklar |
|---|---|---|---|
| T1 | 1-10 | Hagrid'in açıklığı (-280,-20), sera terası (-175,-120), kayıkhane kıyısı (-190,64) | Zayıf inferi, Orman Örümceği (küçük acromantula), Cornish Pixie sürüleri |
| T2 | 10-20 | Yasak Orman batı/güneybatı (`forest_w`, `forest_sw`), köy çevresi | Acromantula, inferi, **Orman Trolü** (3'lü pack) |
| T3 | 20-32 | Mezar tepesi (`crypt_knoll` -640,-180), derin orman, Örümcek Çukuru | İnferi Büyücüsü, Acromantula elit, **Nehir Trolü** (göl kıyısı) |
| T4 | 30-42 | Kaçakçı sırtı (-440,-720), Kuzey bozkırı (`north_moor`) | Kara Kapkaççılar, **Dağ Trolü** (solo/ikili), Haydut büyücüler |
| T5 | 40-55 | İstasyon kıyısı sisi (610,260), Taş Çember (280,-760), yaylalar | **Ruh Emiciler** (gece güçlenir), Ruh Emici Sürüsü |
| World Boss | — | Örümcek Çukuru, kaçakçı kampı (mevcut) + Yayla Zirvesi + Taş Çember | Matriarch (25), Commander (20), **Grak — Dağ Trolü Reisi (38)**, **Azkaban Gardiyanı (50)** |

- `regions[]`'a `level_min/level_max/display` eklenir; oyuncu bölgeye girince ekranda **"Yasak Orman — Sv 10-20"** başlığı ve minimapte renkli bölge (yeşil/sarı/kırmızı = oyuncu seviyesine göre).
- Seviye farkı kuralı (Metin2): oyuncudan **≥10 seviye düşük** moblar az exp + az drop verir; **≥8 seviye yüksek** mobta isabet/hasar cezası. `combat.json → level_gap` bloğu.

### M0.3 Spawn mantığı genişletmeleri

| Özellik | Açıklama |
|---|---|
| **Elit / "Güçlü" mob** | Her normal spawn'da %3 şansla elit: ×3 HP, ×1.5 hasar, altın isim etiketi, kesin loot. `pack_tuning.elite_chance` |
| **Gece/gündüz** | Mevcut gün döngüsü varsa bağlanır; yoksa sunucu saatinden basit faz. Ruh emiciler gece 2× spawn + %20 güç; gündüz sadece sisli bölgede |
| **Devriye** | Bazı packler (`"patrol": [noktalar]`) rota üzerinde yürür — Troller köprü/yol devriyesi |
| **Agresif bölgeler** | T4-T5'te `aggro_mode: "aggressive"` (yakınlıkla saldırır); T1-T3 reactive kalır (acemi dostu) |
| **World boss zamanlayıcı** | `respawn: "scheduled"` → sabit aralık (ör. 2 saat ± 15 dk), spawn'dan 5 dk önce sunucu duyurusu: "Yayla'da yer sarsılıyor…" |
| **Tür bazlı loot** | `loot_tables.json` → `mob` tek tablo yerine `tables: {troll, dementor, …}` + seviye bandına göre drop ölçekleme + mevcut `mob` tablosu varsayılan |

### M0.4 Yetenek / boss mekaniği kütüphanesi

`boss_patterns` → `abilities.json` (yeni). Mevcut `directional` + `area` korunur, eklenecekler:

| Tür | Örnek kullanım | Telegraph (istemci) |
|---|---|---|
| `cone_sweep` | Ejderha nefesi, kafa sırayla tarar | Dönen koni dekali |
| `charge` | Trol hücumu, Kabarık atılması | Ok/şerit dekali |
| `projectile_lob` | Trol kaya fırlatma, ateş topu yağmuru | Hedef zemin halkası |
| `ground_zone` | Salya/lav birikintisi, ruh emici soğuğu | Kalıcı zemin efekti (n sn) |
| `summon` | Yavru ejderha, ruh emici çağırma | Çağırma efekti |
| `grab` | Ruh Emici "Öpücük" — bir oyuncuyu kilitler, diğerleri X hasar vurarak kurtarır | Oyuncu üstünde kırık kalkan barı |
| `aura` | Ruh emici: yakınındakilerin mana/HP yenilenmesini keser | Soğuk sis halkası |
| `phase` | HP %'sinde faz değişimi (yeni yetenek seti, uçuş, enrage) | Ekran duyurusu |
| `enrage_timer` | Zindan bosslarında savaş süresi dolunca öfke | Sayaç |

Tümü mevcut **anticipation → release → recovery** + "release tick'i sunucu yayınlar" sözleşmesine oturur; yani istemci uyarıyı, sunucu hasarı aynı saatle uygular.

**Tehdit (aggro) tablosu:** Şu an hedef = ilk vuran. Zindan için `threat` = hasar + iyileştirme×0.5 + yakınlık bonusu; boss en yüksek tehdide döner, bazı yetenekler "rastgele uzak oyuncu" hedefler (pozisyon önemli olsun).

**Test:** `tests/` altına `mob_catalog_sim`, `abilities_sim` (her yetenek türü: telegraph tick = hasar tick, menzil dışı = 0 hasar).

---

## Faz M1 — Yeni yaratıklar: Troller ve Ruh Emiciler

### Troller (`family: troll`)

Tek humanoid rig, 3 varyant (Meshy retexture + ölçek):

| Mob | Sv | Bölge | Özellik |
|---|---|---|---|
| Orman Trolü | 12-20 | Yasak Orman | Yavaş, ağır sopa; 3'lü pack |
| Nehir Trolü | 22-30 | Göl kıyısı | Su sıçratma (yavaşlatma alanı) |
| Dağ Trolü | 30-40 | Kuzey bozkırı, yayla | Solo/ikili, kaya fırlatma |
| **Grak, Dağ Trolü Reisi** (world boss) | 38 | Yayla Zirvesi (280,-760 yakını) | Faz 1: sopa savurma (koni), yere vurma (alan + sersemletme), kaya fırlatma; **%50'de öfke**: hücum + iki Dağ Trolü çağırma; ölünce büyük gövde çöküşü |

Ortak trol yetenekleri: `club_slam` (alan, 1.2 sn uyarı), `stomp` (yakın halka, sersemletme), `boulder` (projectile_lob). Zayıflık: **Stupefy'a karşı dirençli** (kalın kafa — `stun: 0.5`), **ateşe normal**. Bombarda'ya ×1.2 (sahnede patlamayla yere düşer).

### Ruh Emiciler (`family: dementor`)

| Mob | Sv | Bölge | Özellik |
|---|---|---|---|
| Ruh Emici | 40-48 | İstasyon kıyısı sisi, Taş Çember | Süzülür (yerçekimsiz), `aura`: yakında HP/mana yenilenmesi durur, ekran kenarı buzlanır |
| Ruh Emici Sürüsü | 45-52 | Aynı, gece | 5'li, aggressive |
| **Azkaban Gardiyanı** (world boss) | 50 | Taş Çember, **sadece gece** | `grab` "Öpücük" (bir oyuncu kilitlenir, 6 sn içinde diğerleri kurtarmazsa ağır hasar), soğuk alanlar (`ground_zone`), %60/%30'da 3'er Ruh Emici çağırır; tüm ışıklar söner (atmosfer) |

Patronus konusu → **Kararlar #3**.

### Sanat üretimi — `art/pipeline/MODEL_GENERATION.md` hattı (süpürgede kanıtlandı, ~$2-3/varlık)

```
1. Ana görsel   openai/gpt-image-2.5/sunburst/text-to-image (yan profil, A-poz, beyaz zemin) ← SENİN ONAYIN
2. Görünümler   openai/gpt-image-2.5/sunburst/edit → arka · üst · 45° (paralel)
3. 3D           fal-ai/hunyuan-3d/v3.1/pro/image-to-3d
                  input_image_url=ana · back_image_url=arka · top_image_url=üst · left_front_image_url=45°
                  enable_pbr, face_count 40000 (alt sınır)
                YEDEK: meshy/v7.1/multi-image-to-3d aynı 4 görselle (Hunyuan 504 verirse)
4. Blender      decimate ~4-8k tris + yüksek modelden albedo/normal bake (1024 px), eksen/ölçek/pivot
5a. Humanoid    fal-ai/meshy/rigging (+ multi-animation: idle/walk/attack/death) — düşürülmüş GLB ile
5b. Humanoid değil → Blender headless oto-rig scripti (iskelet şablonu + automatic weights) + script klipler
6. Özel klipler fal hunyuan-motion → retarget_clip.py (mevcut hat)
7. Oyuna al     client/assets/models/monsters/ + mob_*.tscn + LOD + low preset kontrolü (Intel iGPU)
8. Ses          ElevenLabs SFX (mevcut hat)
```

- **Trol** → 4a (humanoid, Meshy rig sorunsuz).
- **Ruh emici** → 4a gövde üstü + **pelerin vertex-shader dalgalanması**, bacak yok (süzülme); el uzatma klibi hunyuan-motion'dan.
- Pelerin/kumaş için fizik simülasyonu YOK (iGPU) — shader ile.

---

## Faz M2 — Parti + Instance + Zindan Altyapısı (zindanlar için şart)

### M2.1 Parti sistemi (protokol v14)

- En fazla **5 kişi**; davet / kabul / ayrıl / at / lider devri. Komutlar: sağ tık oyuncu → "Partiye davet", `/party`.
- HUD: sol üstte parti çerçeveleri (isim, seviye, HP/mana barı, harita uzakta ise gri).
- **Exp paylaşımı**: 40 m içindeki üyeler; Metin2 tarzı parti bonusu (+%10 / kişi, en fazla +%40), seviye farkı > 15 olana pay yok.
- **Loot**: kişisel loot (her üye kendi rulosunu görür) — kavga yok, uygulaması en basit. Para paylaştırılır.
- Sunucu: `authority.gd`'de `parties` kaydı, parti oyun oturumu boyunca yaşar (kalıcı değil).
- İstemci kopyası: `dev.ps1 sync-sim` + `sync-world` (bilinen tuzak).

### M2.2 Instance (kopya harita)

Haritalar şu an **y-bandı** ile ayrılıyor. Zindanlar da yeni y-bantları alır (çakışmasın diye):

| Harita | y-bandı | Not |
|---|---|---|
| grounds | -30 … 185 | mevcut |
| castle_interior | 185 … 400 | mevcut |
| `dng_forbidden_corridor` | 1000 … 1200 | instanced |
| `dng_dragon_lair` | 1400 … 1700 | instanced |

**Her kopya** aynı y-bandında ama **x ekseninde 3000 m kaydırılmış** olarak oluşturulur (kopya k → x + 3000·k). Böylece:
- Sunucu tek fizik dünyasında kalır (ayrı `World3D` yönetimi gerekmez), kopyalar birbirine asla değmez.
- `entity record`'lara `instance_id` eklenir; **ilgi filtresi** (interest filter) sadece aynı instance'ı yayınlar.
- Eşzamanlı kopya sınırı: zindan başına 8 (`maps.json → instance_cap`); dolunca "Zindan dolu, sıradasınız" kuyruğu.
- Boş kalan kopya 5 dk sonra kapanır; ölü/ayrılan üye 10 dk içinde geri dönebilir.

### M2.3 Zindan yaşam döngüsü + script motoru

`addons/hpmmo_sim/data/dungeons.json` (yeni) + `dungeon_director.gd` (authority içinde):

```jsonc
"forbidden_corridor": {
  "map": "dng_forbidden_corridor",
  "level_min": 30, "party_min": 1, "party_max": 5,   // tek kişi de girebilir ama ölçeklenir
  "entries_per_day": 3,
  "time_limit_s": 2400,
  "scale_by_party": { "1": 0.45, "2": 0.6, "3": 0.75, "4": 0.9, "5": 1.0 },
  "steps": [
    { "id": "s1", "on": "enter",            "do": ["spawn:wave_armor_1", "msg:corridor_intro"] },
    { "id": "s2", "on": "all_dead:wave_armor_1", "do": ["open_gate:gate_a"] },
    { "id": "boss", "on": "area:fluffy_hall", "do": ["lock_gates", "spawn:fluffy", "music:boss"] },
    { "id": "end",  "on": "dead:fluffy",    "do": ["open:trapdoor", "spawn_chest:reward", "portal:exit"] }
  ]
}
```

- **Tetikleyiciler**: `enter`, `area`, `all_dead`, `dead`, `hp_below`, `interact`, `timer`.
- **Eylemler**: `spawn`, `open_gate/lock_gates`, `msg` (ekran yazısı), `music`, `spawn_chest`, `portal`, `set_checkpoint`.
- **Wipe**: tüm parti ölürse → son checkpoint'te diriliş, boss tam HP'ye döner (mevcut `encounter_reset` + ödül iptali mekanizması yeniden kullanılır).
- **Kalıcılık**: günlük giriş hakkı ve ilk-kez-temizleme kayıtları `quests` jsonb'ye (mevcut desen, ayrı migration gerekmez) — `dungeons: {forbidden_corridor: {day: "...", entries: 2, clears: 5}}`.
- **Giriş**: lider portala dokunur → seviye + hak kontrolü → 10 sn hazır kontrolü penceresi → bölgedeki parti üyeleri ışınlanır.

**Testler (hedefli):** `party_sim` (davet/exp paylaşımı), `instance_sim` (2 parti → 2 ayrı kopya, birbirini görmüyor, kopya kapanışı), `dungeon_script_sim` (adım zinciri, wipe → checkpoint). `multiplayer_sim`'e 2 istemcinin aynı partide aynı kopyaya girdiği senaryo.

---

## Faz D1 — Zindan: **Yasak Koridor** (Kabarık)

### Giriş — kalede, 3. kat

- `art/castle/layout.json`: **L3 Doğu Koridoru** (`east_corridor_L3`, x 26-86, z -12…-4) — 3. katta koridor dışında oda yok, güney tarafı (z -42…-15) boş. Filmdeki gibi: koridorun **sağ (güney) duvarında kilitli bir kapı**.
- Kapının önünde: "Sağ taraftaki üçüncü kat koridoru yasaktır" tabelası, Filch NPC'si (zindan bilgisi + günlük hak).
- Kapı **Alohomora etkileşimi** (E tuşu, 1.5 sn kanal efekti) ile açılır → zindan portalı. (Alohomora büyü olarak değil, etkileşim animasyonu olarak.)
- Değişiklik: `make_layout.py`'ye kapı + küçük ön oda, `maps.json`'a portal; `bash art/castle/rebuild.sh`.

### Zindan akışı (Sv 30+, 1-5 kişi ölçekli, hedef süre 20-25 dk)

```
[Kilitli Kapı] → 1. Yasak Koridor ──kapı──▶ 2. Zırh Galerisi ──▶ 3. Şeytan Kapanı Mahzeni
                 (trash: pixie +           (mini-boss:           (ortam bulmacası +
                  zırh muhafızları)          Lanetli Zırh)          mini-boss)
                                                                        │
                    6. Ödül Odası ◀── kapak açılır ◀── 5. KABARIK'IN SALONU ◀── 4. Arp Merdiveni
                    (sandık + çıkış)                   (FINAL BOSS)             (gauntlet)
```

| # | Oda | İçerik | Mekanik |
|---|---|---|---|
| 1 | **Yasak Koridor** | 2 pack Cornish Pixie sürüsü (8'li, düşük HP, hızlı), 2 Zırh Muhafızı | Pixie'ler oyuncuyu havaya kaldırıp düşürür (küçük knockup) |
| 2 | **Zırh Galerisi** (mini-boss) | **Lanetli Zırh Komutanı** + duvar boyu zırhlar | %70/%40'da duvardaki 2 zırh canlanır; kalkan duruşu (önden hasar -%80, arkadan vur) |
| 3 | **Şeytan Kapanı Mahzeni** | Sarmaşık dolu oda, mini-boss **Şeytan Kapanı Kökü** | Sarmaşıklar oyuncuyu `root`'lar; **Incendio** sarmaşığı yakar (`resist.fire = -1.0` → ×2), filmdeki çözüm. Kök 3 sarmaşık kolunu yakınca açığa çıkar |
| 4 | **Arp Merdiveni** | Döner taş merdiven, kırık arp parçası (zindanın anahtarı) | Kabarık'ın uyuyan nefesi merdivenden rüzgâr dalgası olarak iner (periyodik itme, kenardan düşmeyin) |
| 5 | **Kabarık'ın Salonu** (final) | Büyük taş salon, ortada **tuzak kapak**, köşede **büyülü arp** kaidesi | Aşağıda |
| 6 | **Ödül Odası** | Kapağın altı: kişisel sandık, çıkış portalı | — |

### Final Boss: **Kabarık** (üç başlı köpek) — Sv 34, ~14.000 HP (5 kişi)

Üç başın **ayrı HP barı** var (Sol / Orta / Sağ) + gövde barı = başların toplamı. Kafa öldürünce o kafa "bayılır" (sarkar), yeteneği kapanır.

| Faz | Tetik | Yetenekler |
|---|---|---|
| **1 — Uyanış** | Başlangıç | **Isırık** (her baş kendi önüne koni, sırayla), **Pençe vuruşu** (ön alan), **Kuyruk** (arkaya süpürme — arkada duranı cezalandırır) |
| **Arp mekaniği** | Her ~45 sn | Bir oyuncu kaidedeki arpa **6 sn kanal** yaparsa (hasar alırsa kesilir) müzik başlar: **3 baş da 10 sn uyur**, alınan hasar **+%50**. Arp sonra 45 sn "akortsuz" (bekleme). Filmdeki gibi |
| **2 — Öfke** | Bir baş bayılınca | Kalan başlar: **Üçlü Kükreme** (oda geneli korku: 2 sn kontrol kaybı — Protego engeller), **Atılma** (`charge`, en uzak oyuncuya) |
| **3 — Çılgınlık** | Toplam %25 | **Salya birikintileri** (`ground_zone`, yavaşlatma + hasar), arp artık 5 sn uyutur; 8 dk'da `enrage_timer` |

Ölüm: köpek yere çöker, kapak açılır (anim + ses) → ödül odası.

Ödüller:
- **Kabarık'ın Tasması** (yeni aksesuar yuvası değilse → cüppe efsunu taşıyıcı nadir malzeme; Kararlar #5)
- **Arp Teli** (yeni malzeme, asa yükseltme)
- Mevcut: `scroll_imbue`, `scroll_reweave`, galleon, `mat_dragon_heartstring`
- İlk temizleme: unvan **"Yasak Koridor Kâşifi"**

### Sanat listesi (D1)

| Varlık | Üretim |
|---|---|
| **Kabarık** | 4 görünüm → Hunyuan 3D → decimate+bake → **Blender oto-rig**: omurga + 3 boyun zinciri + 3 kafa/çene + 4 bacak + kuyruk; klipler: idle (nefes), uyku, yürüme, ısırık×3 kafa, pençe, kükreme, atılma, ölüm |
| Cornish Pixie | 4 görünüm → Hunyuan 3D → basit rig (gövde+kanat çırpma prosedürel) |
| Zırh Muhafızı / Komutanı | 4 görünüm → Hunyuan 3D → Meshy humanoid rig |
| Şeytan Kapanı | Blender prosedürel sarmaşık (curve + bone chain), kök gövdesi Meshy |
| Arp, tuzak kapak, kapı | Meshy hero prop (ITEM_3D_PIPELINE) |
| Mekan | Mevcut Gotik kit + `gothic_dress.py` + Poly Haven dokuları; düzen `art/dungeons/forbidden_corridor/layout.json` (castle generator'ı yeniden kullanılır) |
| Konseptler | Her oda için 1 atmosfer konsepti (fal) — onayına sunulur |

---

## Faz D2 — Zindan: **Ejderha Yuvası** (Macar Dikkuyruk)

### Giriş

**Romanya Ejderha Koruma Alanı** temalı: Hagrid'in kulübesi yanında (-280,-20) **Charlie Weasley** benzeri bir ejderha bakıcısı NPC'si (IP için isim özgün: "Ejderbilimci Radu") → **Portkey** (eski bir çizme). Kısa giriş görevi: "Yuvaya saldıran kaçak avcıları durdur". (Alternatif: haritada mağara girişi — Kararlar #4.)

### Zindan akışı (Sv 45+, 3-5 kişi önerilir, 1 kişiyle ölçekli ama çok zor; hedef 35-45 dk)

```
Portkey ─▶ 1. Kömür Kanyonu ─▶ 2. Avcı Kampı ─▶ 3. Kuluçka Mağaraları ─▶ 4. Lav Köprüsü ─▶ 5. DİKKUYRUK'UN YUVASI ─▶ Hazine
           (trash)              (mini-boss 1)    (mini-boss 2 + savunma)   (gauntlet)         (FINAL, 3 faz)
```

| # | Bölüm | İçerik | Mekanik |
|---|---|---|---|
| 1 | **Kömür Kanyonu** | Kaçak avcı büyücüler (darksnatcher rig'i yeniden + yeni doku), **Ateş Semenderleri** (küçük, sürü), Ateş Sümüklüleri | Semenderler öldüğünde küçük alev alanı bırakır |
| 2 | **Avcı Kampı** (mini-boss 1) | **Avcıbaşı Vardan** + zincirli **Gal Yeşili yavru ejderha** | Avcıbaşı ağ atar (`root`), zincir direklerine vurulursa yavru serbest kalır ve **avcıya saldırır** (müttefik NPC — ödül bonusu) |
| 3 | **Kuluçka Mağaraları** (mini-boss 2) | Yumurta yuvaları, **Çin Ateştopu** (yetişkin, yerde savaşır) | Savunma: dalgalar halinde semenderler yumurtalara saldırır; yumurta kırılırsa Ateştopu **öfkelenir** (+hasar). Yumurtaları koru = kolay boss. Ahlaki/temalı seçim |
| 4 | **Lav Köprüsü** | Dar taş köprü, altında lav | Dikkuyruk tepeden **alev şeritleri** atar (`cone_sweep` telegraph'ı yerde şerit), kayalık siperler arası koşu; köprü ortasında 2 dalga yavru ejderha |
| 5 | **Dikkuyruk'un Yuvası** | Kraterli yuva, altın yumurta, 4 kaya sütunu (siper) | Aşağıda |

### Final Boss: **Macar Dikkuyruk** — Sv 52, ~60.000 HP (5 kişi), 10 dk enrage

| Faz | HP | Yetenekler |
|---|---|---|
| **1 — Yerde** | 100-65 | **Isırık** (ön koni, tehdit hedefine), **Pençe** (ön yarım daire), **Dikenli kuyruk** (arkaya 180° süpürme + kanama), **Alev Nefesi** (`cone_sweep`: 70° koni, soldan sağa 2 sn tarama — arkaya/yana kaç) |
| **2 — Havada** | 65-35 | Kalkış animasyonu; boss **uçar** (vurulamaz bölümler var). **Bombardıman koşusu**: arenadan çizgi halinde alev (`charge` şeridi), **Ateş topu yağmuru** (`projectile_lob` × 6, rastgele oyuncular), **kaya sütunları** arkasına saklan: tam-oda alev nefesi (sütun olmayan her yer). Her nefes bir sütunu **çatlatır** (4 sütun = sınırlı tolerans). Bu sırada 4 **yavru ejderha** iner |
| **3 — Yaralı öfke** | 35-0 | İner, kanatları yırtık (artık uçamaz). **Lav çatlakları** (`ground_zone` zemin genişler, alan daralır), kuyruk dikenleri fırlatma (koni projeksiyon), %10'da **son nefes**: ekranın yarısını kaplayan alev, güvenli yarıyı telegraph gösterir |

Ölüm: uzun çöküş animasyonu, yuvadaki altın yumurta etkileşimi → ödül.

Ödüller:
- **Ejderha Pulu Seti** (cüppe + asa süsü; yeni item, mevcut item instance/efsun sistemiyle — `uid + bonuses`)
- **Dikkuyruk Diken'i** (asa yükseltmenin üst kademeleri için nadir malzeme)
- **Altın Yumurta** (koleksiyon/görev eşyası)
- Mevcut: `mat_dragon_heartstring` (garanti 3-5), `mat_elder_core` şansı, efsun parşömenleri
- İlk temizleme: unvan **"Ejderha Terbiyecisi"** + binek ileride (kapsam dışı, not)

### Sanat listesi (D2)

| Varlık | Üretim |
|---|---|
| **Dikkuyruk** | 4 görünüm (kanatlar açık; kapalı poz ayrıca) → Hunyuan 3D → decimate+bake → **Blender oto-rig**: omurga, boyun 4, kafa+çene, 4 bacak, kuyruk 8, 2 kanat (her biri 4 kemik). Klipler: idle, yürüme, ısırık, pençe, kuyruk süpürme, nefes (taramalı), kalkış, uçuş döngüsü, havada nefes, iniş, ölüm. **En riskli varlık** (aşağıya bkz.) |
| Çin Ateştopu | Dikkuyruk iskeletini **yeniden kullanır** (aynı kemik isimleri) → klipler paylaşılır, sadece mesh + doku farklı |
| Gal Yeşili yavru, yavru ejderhalar | Aynı iskelet, küçük ölçek |
| Semender, Ateş Sümüklüsü | Meshy + basit prosedürel rig (spider_rig.gd tarzı) |
| Avcı büyücüler | Mevcut darksnatcher rig'i + Meshy retexture |
| Mekan | Volkanik kanyon: Blender prosedürel kaya/kanyon + Poly Haven volkanik dokular + lav shader (düşük presette emission-only) |
| VFX | Ejderha ateşi, lav, kor parçacıkları — mevcut **Wan → flipbook** hattı |
| Ses | Kükreme ×3, kanat çırpma, nefes, yere iniş — ElevenLabs |

---

## Riskler ve önlemler

| Risk | Etki | Önlem |
|---|---|---|
| **Dört ayaklı/kanatlı rig** (Kabarık, ejderha): fal'da humanoid olmayan otomatik rig yok | Animasyon kalitesi | Blender headless oto-rig scripti (bilinen iskelet şablonu → mesh bounding'e oturt → automatic weights) + script ile anahtar kare klipler. **Önce Kabarık'ta prototip**, sonra ejderhaya taşı. Olmazsa yedek: parçalı prosedürel rig (spider_rig gibi, eklemli parçalar) |
| Meshy çok-başlı modeli yanlış birleştirir | Kabarık | 4 görünüm konsept + `tripo3d/segment` ile kafa ayırma; olmazsa kafaları ayrı üretip Blender'da birleştir |
| Intel iGPU performansı | Ejderha arenası, lav, parçacıklar | Her varlık LOD + low presette çekirdek VFX katmanları (mevcut kural); arena `--perf --quality=low` ölçümü |
| Instance x-ofsetinde fizik/gölge mesafeleri | Uzak kopyalar | Kopyalar sadece sunucuda fiziksel; istemci sadece kendi kopyasını yükler (lokal koordinat dönüşümü) |
| Protokol + sync tuzakları | Sunucu eski mantıkla koşar | Her fazda `sync-sim` + `sync-world` + yeniden import (bilinen tuzaklar) |
| IP | Sürümler GitHub Releases'ta | Özgün tasarım ("filmden esinli, birebir değil"), NPC isimleri özgün; Kabarık/Dikkuyruk tür adları kalır |

---

## fal.ai maliyet tahmini (düzeltildi)

İlk taslakta gpt-image'in "1 unit" fiyatını yanlışlıkla "görsel başına $1" saydım — yanlış. Gerçek
referans: süpürge pilotu, bütün hat (ana görsel + 3 görünüm + 3D) **~$2-3**.

| Kalem | Adet | Tahmini |
|---|---|---|
| Yaratık (4 görsel + Hunyuan 3D, +%50 tekrar payı) | ~13 | ~$35-50 |
| Humanoid rig (Meshy rigging $0.80 + animasyon $0.08) | ~5 | ~$5 |
| Hero prop (arp, kapak, yumurta, kapı, sütun…) | ~12 | ~$25-35 |
| Mekan/atmosfer konseptleri (tek görsel) | ~14 | ~$5-10 |
| Hunyuan-motion klipler, VFX flipbook, SFX | — | ~$10-15 |
| **Toplam (5 faz)** | | **~$80-115** |

Faz başına: M0 $0 (sadece kod) · M1 ~$15-20 · D1 ~$30-40 · D2 ~$35-50. Her toplu işten önce
yine kalem kalem tahmin.

## Uygulama sırası ve kontrol noktaları

| Faz | İçerik | Senin onay noktan | Tahmini oturum |
|---|---|---|---|
| **M0** | mobs.json, resist, bölge seviyeleri + HUD başlığı, elit, tür loot'u, yetenek kütüphanesi, tehdit tablosu | Bölge/seviye tablosu (bu dokümanda) | 1-2 |
| **M1** | Troller + Ruh emiciler + 2 world boss | **Konsept görselleri** → sonra 3D | 2-3 |
| **M2** | Parti, instance, zindan script motoru, giriş/haklar | Parti HUD görünümü | 2-3 |
| **D1** | Yasak Koridor: kale kapısı, 6 oda, Kabarık | Oda konseptleri + Kabarık konsepti + rig prototipi | 3-4 |
| **D2** | Ejderha Yuvası: 5 bölüm, Dikkuyruk 3 faz | Konseptler + ejderha rig/uçuş prototipi | 4-5 |

Her faz sonunda: hedefli testler (sadece değişikliğin gerektirdiği sim'ler — `ready -Full` varsayılan değil), oyunda kısa video/ekran görüntüsü, sonra sıradaki faz.

---

## Kararlar (onay verirken değiştirebilirsin — varsayılanlar kalın)

1. **Parti büyüklüğü:** **5** (alternatif 4).
2. **Kabarık'ın yeri:** **Final boss** (önce koridor/zırh/Şeytan Kapanı, sonda Kabarık, altında kapak) — alternatif: filmdeki sıra (Kabarık ilk, sonra kapaktan aşağı Şeytan Kapanı → uçan anahtarlar → dev satranç → trol); bu ikinci zindan olarak ileride eklenebilir.
3. **Ruh emicilere karşı Patronus:** **Yeni büyü "Expecto Patronum"** (Sv 40'ta açılan görev ödülü; ruh emicilere ×3 hasar + korku kırar). Alternatif: Patronus yok, ruh emiciler sadece Incendio'ya zayıf.
4. **Ejderha zindanı girişi:** **NPC + Portkey** (Hagrid kulübesi yanı). Alternatif: kaçakçı sırtında fiziksel mağara ağzı.
5. **Zindan ödül eşyaları:** **Mevcut yuvalara** (asa/cüppe/süpürge + malzemeler) — yeni aksesuar yuvası (tasma, kolye) açılmaz. Alternatif: aksesuar yuvası ekle (envanter/protokol işi büyür).
6. **Giriş sınırı:** **Günde 3 giriş**, anahtar eşya yok. Alternatif: Metin2 tarzı giriş anahtarı/bileti (drop'tan).
7. **fal hattı:** **MODEL_GENERATION.md** (GPT Image 2.5 → Hunyuan 3D v3.1 Pro, yedek Meshy 7.1).

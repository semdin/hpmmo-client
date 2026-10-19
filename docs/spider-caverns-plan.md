# Kara Ağ Mağaraları — örümcek kasılma haritası + seyahat nesneleri (plan)

> Durum (2026-10-19): **S0 onaylandı, S1 greybox oynanabilir.** Konseptler `art/spider_caverns/concepts/`,
> ek görünümler `views/`, Hunyuan ham modeller `raw/` (5/5 başarılı), bake edilmiş proplar `game/`
> (taş 4k, şömine 4k, çizme 2k tri). Harita: `art/spider_caverns/layout.json` → `scripts/cavern_heightfield.py`
> → `scripts/cavern_mesh_blender.py` (175 chunk, 358k tri, LOD'lar import'ta) + `client/tools/maps/build_cavern_collision.gd`
> (HeightMapShape3D 513²). Oyunda: `scenes/world/caverns/spider_caverns.tscn` (yalnız görsel), çarpışma her süreçte
> dünya açılışında kalıcı (`cavern_colliders.gd`, maps.json `collision`), atmosfer `cavern_atmosphere.gd`
> (maps.json `atmosphere: "cavern"`), map_controller'da "sahne haritası" (`_scene_map`), sunucu map_host aynı.
> Portallar: `crypt_descend` (grounds, mahzen kapısı) ↔ `caverns_ascend` (merdiven dibi); kamp güvenli bölge.
> Gidiş-dönüş `tools/capture/portal_probe.tscn` ile doğrulandı.
> **S2 (2026-10-19):** Zehirdiş + Kuluçka Muhafızı: `creature_prepare.py` → `art/pipeline/scripts/spider_rig.py` (ayak adaları
> → bacak zincirleri, 10 bacak/taraf 5 da olabilir; klipler Idle/Walk/Turn/Bite/Spit/Leap/Hit/Stun/Death). Yetenekler:
> `poison` (yanma saatinde zehir, `apply_poison`) ve `web_s` (yayan %50 hız, `apply_web`, player.gd `WEBBED_FACTOR`,
> stats payload `webbed_until_tick`). Mağara spawn'ları `art/spider_caverns/scripts/cavern_spawns.py` (43 paket / 191 yaratık,
> agresif, `respawn_s` 12-18, `clear_radius` 5, paket `y` = zemin), bölgeler `caverns_f1/f2` (`map`), loot `cavern_spider`.
> Doğrulama: `tools/capture/cavern_probe.tscn` (zemine oturma, zehir/ağ tetiklenmesi).
> **S3 (2026-10-19):** `spawn_tables.monolith_types` (dark = eski monolith_config, spider), `monoliths[].type`;
> `dark_monolith.gd` türden okur (isim/seviye/can/exp/dalga/loot/respawn, `_ground_y` mağarada ışın), sahne
> `scenes/entities/monolith/spider_stone.tscn`. Protokol **v19**: mob variant 14/15 (Zehirdiş/Muhafız — S2'de eksikti,
> uzak istemciler inferi görürdü) ve 16 = Mühür Taşı (monolith kaydı `variant` taşır). 5 taş (kat 1: 2, kat 2: 3),
> Sv 30, 9000 can, 3 dk respawn, loot `monolith_spider`. Yeni eşyalar: `mat_spider_silk`, `mat_acromantula_venom`,
> `queen_seal` (taştan %8, örümceklerden %0.15; S6 Kraliçe Odası anahtarı). İkonlar sunburst ile.
> **S4 (2026-10-19, protokol v20):** `addons/hpmmo_sim/data/travel.json` (5 şömine: Avlu, Hogsmeade, Hagrid, Büyük Salon,
> Kara Ağ Kampı; `floo` kuralları), `HPMaps.travel*`, authority `request_travel` (öğrenme + yolculuk; aynı harita da
> transfer akışından, `floo:<id>` spawn), transfer rezervasyonu ortak `_grant_transfer`. `floo_known` quests jsonb'de,
> stats payload'da. Uçuç Tozu (`floo_powder`, `buy_price` 2.500 — equipment `buy` işlemi, pencereden), taş %25 / örümcek %2.
> İstemci: `TravelNodes` (şömineler, ocak ateşi, yeşil alev `burst` + `floo_whoosh` sesi), `HudFloo` penceresi,
> map_controller F istemi / kalkış-varış alevi. Doğrulama `tools/capture/floo_probe.tscn` (4 yolculuk + ret + satın alma).
> Not: kalkış alevini yalnızca yolcu görüyor (diğer oyunculara yayın yok). Görüntüler: `tools/capture/world_shots.tscn -- --map=spider_caverns`. Kararlar bölümündeki varsayılanlarla ilerlenecek;
> her fazın sonunda oyunda gösterilip onay alınır. Konsept görselleri 3D'ye geçmeden önce onaya sunulur.

## Hedef

1. **Yeni harita:** Metin2 Örümcek Zindanı mantığında, herkesin aynı anda kasıldığı **paylaşımlı** (instance değil)
   bir mağara haritası. Sv 24–32. Girişi arazideki **Lanetli Mahzen**'in (`crypt`, -640,-180) altından.
2. **2 yeni örümcek türü** (Acromantula'dan belirgin şekilde güçlü) + **1 örümcek metin taşı**.
3. **Seyahat nesneleri:** Uçuç Ağı (şömine + Uçuç Tozu), Anahtar (çizme, parti ile toplu ışınlanma);
   sonraki adım olarak Kaybolan Dolaplar ve Tek Gözlü Cadı geçidi.

İsim önerileri (varsayılan ilki): **Kara Ağ Mağaraları** (*Blackweb Caverns*) · Mahzen Altı Yuvası · Ağlı Derinlikler.

---

## 1. Harita — `spider_caverns`

### 1.1 Yerleşim (Metin2 Örümcek Zindanı 1 + 2 tek haritada)

```
 [Lanetli Mahzen merdiveni]                                  harita ~ 480 x 480 m, y-bandı 1500 … 1700
          │
   ┌──────▼───────┐   dar tünel    ┌─────────────────┐   iniş rampası   ┌────────────────────┐
   │ GİRİŞ KAMPI  │ ─────────────▶ │ KAT 1: Ağlı     │ ───────────────▶ │ KAT 2: Yumurta     │
   │ (güvenli,    │                │ Galeriler       │  (~25 m iniş)    │ Mağaraları         │
   │ şömine, NPC, │                │ Sv 24-28        │                  │ Sv 28-32           │
   │ satıcı)      │                │ 4-5 oda+koridor │                  │ 4-5 oda, daha sık  │
   └──────────────┘                └─────────────────┘                  └─────────┬──────────┘
                                                                                  │ mühürlü ağ kapısı
                                                                        ┌─────────▼──────────┐
                                                                        │ KRALİÇE'NİN ODASI  │  (Faz S6, ops.)
                                                                        │ instanced, anahtar │
                                                                        └────────────────────┘
```

- **Paylaşımlı harita** (`instanced: false`, `capacity: 64`): Metin2'deki gibi herkes aynı mağarada, aynı moblar.
- **Kasılma yoğunluğu:** oda başına 2–4 pack, pack başına 4–6 örümcek, `respawn_s` 20–30 sn (araziden çok daha hızlı).
  Hedef: tek oyuncu bir odayı temizlerken ilk pack yeniden doğsun — durmadan kesme döngüsü.
- **Güvenli giriş kampı:** `safe_zones` + şömine + bir NPC (görev/bilgi) + Uçuç Tozu/iksir satıcısı + depo değil.
- **Kraliçe'nin Odası** (S6, isteğe bağlı): Metin2 Barones gibi; metin taşından/elitten düşen **Kraliçe Mührü** ile
  parti giriş yapar; mevcut `boss_matriarch` modeli yeni yeteneklerle yeniden kullanılır (yeni sanat yok).

### 1.2 Heightmap gerekiyor mu? — Evet, ama fal'dan değil, **layout'tan script ile**

Mağara zemini bir yükseklik haritasıdır; fal görselinden üretilen heightmap kontrol edilemez (yürünmez eğimler,
mob yolları bozulur). Arazide zaten çalışan yöntemi aynen kullanıyoruz:

| Adım | Araç | Çıktı |
|---|---|---|
| Yerleşim | `art/maps/spider_caverns/layout.json` (elle): odalar (merkez, yarıçap, zemin yüksekliği), tüneller (yol + genişlik), rampalar, kamp | — |
| Yükseklik | `art/maps/spider_caverns/heightfield.py` (`art/map/scripts/heightfield.py` mantığı): yürünebilir maske → zemin; maskenin dışı 25–40 m'lik gürültülü **kaya duvarı**; zemine düşük frekanslı tümsek | `height.raw` (512², 1 m hücre), `walkable.png`, `stats.json` |
| Doku maskesi | aynı script: kaya / ağlı toprak / kemik-çakıl / balçık kanalları | `splat.png` (RGBA) |
| Oyun içi | `scripts/world/caverns/cavern_builder.gd`: 64 m'lik **chunk mesh** (2 LOD) + sunucuda `HeightMapShape3D` çarpışma; duvar dikliğine göre triplanar kaya shader | sahne `scenes/world/caverns/spider_caverns.tscn` |
| Süsleme | `scatter.py` mantığı: sarkıt/dikit, ağ perdeleri, yumurta kesesi, kemik, koza, parlak mantar (yalnız görsel, çarpışma sadece büyükler) | `scatter_*.bin` |

**Neden Terrain3D değil:** Terrain3D arazi haritasına bağlı (tek bölge seti, grounds park/unpark sistemi) ve y-bandına
taşınması riskli. 480 m'lik bir mağara için kendi chunk mesh'imiz hem daha hafif (iGPU, low preset) hem de tavan
gerektirmiyor: **tavan yok**, duvarlar yüksek + koyu sis + yukarıda siyah tavan düzlemi + kamera tavan sınırı ile
kapalı mağara hissi. (Bu, Metin2'nin kendi örümcek zindanının da yaptığı şey.)

### 1.3 Atmosfer

- Koyu, yeşilimsi-mor ortam ışığı; `WorldEnvironment` volumetrik sis (low preset'te kapalı, düz sis); yumurta keselerinde
  ve mantarlarda zayıf `OmniLight3D` (en fazla ~12 gölgesiz ışık / ekran).
- Ses: mevcut audio director'a yeni bölge `spider_caverns` (damla, cıvıltı, uzak tıkırtı; ElevenLabs SFX + bir müzik döngüsü).
- Harita: dünya haritasında (M) ayrı sayfa + oda isimleri; minimapte kamp ve rampa.

### 1.4 Sunucu/veri değişiklikleri

- `maps.json`: `spider_caverns` (y 1500–1700, `flight_allowed: false`, `safe_zones: ["caverns_camp"]`,
  `respawn_spawn: "camp"`), portallar `crypt_descend` (grounds → caverns) ve `caverns_ascend` (geri).
- Grounds tarafı: `GroundsSites._crypt` — mahzenin önüne açık merdiven ağzı + kapı (`dressing: "crypt_stairs"`).
- `spawn_tables.json`: `spider_caverns` bölgeleri (`map` alanı ile), packlar ve seviye bantları. Pack'lerin haritaya
  ait olduğu y-bandından anlaşılır; spawn yerleri `walkable.png`'den seçilir (generator: `wild_spawns.py` tarzı).
- Sunucu dünyası: `server/world/` kopyası `dev.ps1 sync-world` ile; çarpışma sunucuda da yüklenir.

---

## 2. Yeni yaratıklar

| | **Zehirdiş Akromantula** (`acromantula_venomfang`) | **Kuluçka Muhafızı** (`acromantula_broodguard`) |
|---|---|---|
| Rol | Uzaktan/çevik — kat 1 ve 2 | Ağır/tank — sadece kat 2 + metin taşı dalgaları |
| Seviye | 26–30 | 29–32 |
| Güç (Acromantula'ya göre) | HP ×2.2, atak ×1.6, hız 8.5 | HP ×4, atak ×2, hız 6.5, büyük gövde (×1.6 ölçek) |
| Yetenekler | **Zehir tükürüğü** (menzilli bolt, 6 sn zehir DoT), **Zehir birikintisi** (`ground_zone`, ölünce bırakır) | **Ağ atışı** (hedefi 2 sn yavaşlatır, %50), **Sıçrayış** (`charge`), **Zırhlı kabuk** (önden %40 hasar azaltma — `front_guard` mevcut mekanizma) |
| Direnç | ateş -0.25, zehir 0.5 | ateş -0.25, fiziksel 0.2 |
| Loot | `spider_caverns` tablosu: Akromantula zehri, ipek, efsun parşömeni, T3–T4 ekipman | + **Kraliçe Mührü** parçası (düşük şans) |
| Exp | `exp_mult` 1.4 | `exp_mult` 2.0 |
| Görünüm | ince, uzun bacaklı, zümrüt zehir bezeleri, parlak yeşil desen | iri, kemik-zırh plakalı, kırmızı göz kümesi, sırtında yumurta kesesi |

Mevcut `acromantula` (Sv 14) ve elitleri kat 1'in giriş odalarında dolgu olarak kalır.

**Üretim (kullanıcının akışı, `art/pipeline/MODEL_GENERATION.md`):**
1. `openai/gpt-image-2.5/sunburst/text-to-image` — ana görünüm (yandan, beyaz zemin).
2. `openai/gpt-image-2.5/sunburst/edit` — arka, üst, 45° görünümleri.
3. `fal-ai/hunyuan-3d/v3.1/pro/image-to-3d` — 4 görünüm (`back_image_url`, `top_image_url`, `left_front_image_url`);
   hata verirse **Meshy 7.1 multi-image** aynı 4 görselle.
4. Blender: decimate (40k → ~8k tri) + normal/renk bake (1024 px) — `creature_prepare.py`.
5. Rig + klipler: Acromantula'nın 8 bacaklı iskeleti/klip seti (`anim_set "spider"`) **yeniden kullanılır**;
   yeni mesh'e oturtma `wraith_rig.py`/`hound_rig.py` tarzı orantısal rig + voxel proxy ağırlık aktarımı
   (bilinen Hunyuan bone-heat tuzağı). Klipler: Idle, Walk, Turn, Attack, (yeni) Spit, Leap, Death.

---

## 3. Örümcek Metin Taşı — **Ağlı Mühür Taşı** (`monolith` tür: `spider`)

- Şu an `dark_monolith` tek tür ve `monolith_config` tek blok. Genelleştirme:
  `spawn_tables.json → monolith_types: { "dark": {...mevcut...}, "spider": {...} }`, her `monoliths[]` girdisi
  `type` + map'e göre konum alır; `dark_monolith.gd` → türden model, ışık rengi, isim, dalga ve loot okur.
- **Spider:** Sv 30, ~9000 HP, 3 dalga (%75 / %50 / %25): Zehirdiş ×3 → Zehirdiş ×3 + Muhafız ×1 → Muhafız ×2 + yavru sürüsü.
  Kat 1'de 2, kat 2'de 3 taş; yeniden doğma 3 dk (ilk sürümde 30 sn olan genel değer yerine tür bazlı `respawn_ms`).
- Loot (`monolith_spider`): galleon, efsun/yeniden dokuma parşömenleri, örümcek malzemeleri, **Kraliçe Mührü** (%8),
  Uçuç Tozu (%25).
- Görünüm: ağlarla sarılmış kara obsidyen dikilitaş, gövdesine gömülü yumurta keseleri, mor-yeşil iç ışık.
  Üretim: sunburst → edit → Hunyuan → `prop_prepare.py` (Dark Monolith ile aynı yol).

---

## 4. Seyahat sistemi — ortak altyapı

Bir veri dosyası, bir sunucu doğrulaması, birkaç görünüm:

```jsonc
// addons/hpmmo_sim/data/travel.json (yeni)
"nodes": {
  "floo_courtyard":   { "kind": "floo", "map": "grounds",        "pos": [...], "label": "Avlu Şöminesi" },
  "floo_hogsmeade":   { "kind": "floo", "map": "grounds",        "pos": [...], "label": "Üç Süpürge" },
  "floo_hagrid":      { "kind": "floo", "map": "grounds",        "pos": [...], "label": "Hagrid'in Kulübesi" },
  "floo_great_hall":  { "kind": "floo", "map": "castle_interior","pos": [...], "label": "Büyük Salon" },
  "floo_caverns_camp":{ "kind": "floo", "map": "spider_caverns", "pos": [...], "label": "Kara Ağ Kampı" }
},
"floo":    { "item": "floo_powder", "cost": 1, "channel_s": 1.5, "radius": 3.0, "level_min_by_node": {"floo_caverns_camp": 24} },
"portkey": { "item": "portkey_boot", "countdown_s": 10, "grab_radius": 3.0, "lifetime_s": 30,
             "destinations": ["caverns_camp", "courtyard", "hogsmeade", "hagrid"] }
```

- **Sunucu (authority):** `sim_travel_request(node_id, dest_id)` → mesafe, seviye, eşya, savaşta olmama
  (son 5 sn hasar yok), zindan içinde olmama kontrolü → eşyayı düşür → aynı haritaysa **harita içi ışınlama**
  (yeni: konum zorla + `sim_push` benzeri düzeltme), farklı haritaysa mevcut `MapController` transferi
  (yükleme ekranı dahil). Hepsi `HPProtocol` reddi kodlarıyla (`REJECT_TOO_FAR`, `REJECT_NO_ITEM`, `REJECT_IN_COMBAT` …).
- **Protokol v19.** `quests` jsonb'ye `travel.floo_known` (ziyaret edilen şömineler — ilk kez yanından geçince açılır,
  Metin2 ışınlanma yüzüğü gibi bilinmeyen yere gidilmez).

### 4.1 Uçuç Ağı — şömine + Uçuç Tozu

- Şömine yanında **E** → *Uçuç Ağı* penceresi (ArcaneSkin, bilinen şömineler listesi, gri = bilinmeyen; Uçuç Tozu adedi).
- Seçince: 1.5 sn kanal — oyuncu şömineye girer, **yeşil alev patlaması** (görsel 1'deki gibi: yeşil duman sütunu +
  kıvılcım), "Diagon…" gibi değil, hedef adı söylenir (ses), sonra transfer; varışta karşı şömineden yeşil alevle çıkış.
- **Uçuç Tozu** (`floo_powder`, stackable 200): Hogsmeade satıcısında 2.500 galleon, metin taşlarından ve görev ödüllerinden.
  İkon: 2D akış (sunburst → kesme).
- Şömine modeli: taş Gotik ocak, iç kısmı is kararmış, yanında toz kabı. 1 model, 5 yerde (kamp versiyonu kaba taş).

### 4.2 Anahtar (Portkey) — eski çizme, parti ile toplu ışınlanma

Akış (Ateş Kadehi sahnesi):
1. Oyuncu envanterde **Eski Çizme**'ye sağ tık → hedef seçme penceresi (`portkey.destinations`).
2. Çizme oyuncunun önüne **yere konur** (sunucuda yeni replike varlık `Kind.PORTKEY`: sahip, parti id, hedef,
   bitiş zamanı). Üstünde mavi parıltı + 10 sn geri sayım halkası; partiye sistem mesajı "X bir Anahtar hazırladı".
3. **Sadece sahibin partisindekiler** çizmeye yaklaşıp **E** ile **tutunur** (diğerlerine "Bu Anahtar sana ait değil").
   Tutunan oyuncu çömelir, eli çizmede, hareket edemez (hareket tuşu = bırak). Sahip otomatik tutunur.
4. Sayaç bitince tutunan herkes **aynı anda** hedefe aktarılır: göbekten çekilme + dönen mavi-beyaz girdap, iniş
   noktasında halka şeklinde yerleştirilir (üst üste binmesin). Çizme tükenir (tek kullanımlık, film gibi).
- Kurallar: zindanda/savaşta kullanılamaz; sayaç sırasında sahip ölür veya tutunan kimse kalmazsa iptal ve çizme iade.
- Kaynak: Hagrid'in kulübesindeki NPC'den 10.000 galleon / görev ödülü / metin taşından nadir drop.
- Model: yıpranmış deri bağcıklı çizme (görsel 2) — tek görsel yeter, ama 3D için 4 görünüm akışı.
- Animasyon: "tutunma" pozu — ilk sürümde mevcut çömelme/etkileşim pozundan; gerekirse
  `fal hunyuan-motion → retarget_clip.py` ile kısa diz çökme klibi.

### 4.3 Sonraki adım (S7): Kaybolan Dolaplar + gizli geçit

- **Kaybolan Dolap çifti** (görsel 3): Kale içinde (İhtiyaç Odası köşesi) ↔ Kara Ağ Kampı'nın derin ucu (kat 2 girişi).
  Ücretsiz, iki yönlü, tek kişi; kapıları açılıp kapanan dolap, içine giren karşıdan çıkar. Kilidi bir görevle açılır.
- **Tek Gözlü Cadı heykeli**: kale 3. kat → Hogsmeade (Balparmak bodrumu). "Dissendium" etkileşimi; Çapulcu Haritası
  görevi ödülü. Aynı `travel.json` altyapısı (`kind: "passage"`), yeni sistem gerektirmez.

---

## 5. Sanat listesi ve maliyet

| Varlık | Akış | Tahmini |
|---|---|---|
| Harita konseptleri (kamp, kat 1, kat 2) | sunburst t2i ×3 | ~$1 |
| Zehirdiş, Kuluçka Muhafızı | sunburst + edit ×3 + Hunyuan + rig | ~$6 |
| Ağlı Mühür Taşı | sunburst + edit + Hunyuan | ~$3 |
| Şömine, Eski Çizme, (S7: Dolap, Cadı heykeli) | sunburst + edit + Hunyuan | ~$6 (+$6) |
| Mağara propları: sarkıt kümesi, dikit, yumurta kesesi kümesi, koza, kemik yığını, parlak mantar, mahzen merdiven ağzı | sunburst + edit + Hunyuan (tek parça propta tek görsel) | ~$15 |
| Zemin dokuları (kaya, ağlı toprak, kemik çakılı, balçık) | Poly Haven (ücretsiz) + 1-2 sunburst tileable | ~$1 |
| İkonlar: Uçuç Tozu, Eski Çizme, Kraliçe Mührü, örümcek malzemeleri | sunburst t2i → `cutout_icons.py` | ~$1 |
| FX: Uçuç yeşil alevi, Anahtar girdabı | fal Wan klip → flipbook (spell FX akışı) | ~$3 |
| Ses: mağara ambiyansı + müzik, 2 tür × (hareket/uyarı/saldırı/ölüm), şömine, anahtar | ElevenLabs | ~$2 |
| **Toplam** | | **~$40 (S7 ile ~$46)** |

Her toplu üretimden önce maliyet tahmini gösterilir; konseptler onaysız 3D'ye gitmez.

---

## 6. Fazlar (sırayla, her faz sonunda oyunda gösterim)

| Faz | İçerik | Onay noktası |
|---|---|---|
| **S0** | Konseptler: harita atmosferi ×3, 2 örümcek, metin taşı, şömine, çizme | Görsel onayı |
| **S1** | Harita: `layout.json` → heightfield → chunk mesh + çarpışma, duvarlar, ışık/sis, `maps.json`, mahzen girişi + çıkış, kamp güvenli bölge, harita sayfası (proplar önce greybox) | `--test-char=28` ile mahzenden inip dolaşma, iGPU FPS |
| **S2** | 2 yeni tür: model + rig + klipler, `mobs.json` + yetenekler (zehir DoT, ağ yavaşlatma), mağara spawn'ları + `spider_caverns` loot tablosu, sesler | Kasılma döngüsü (respawn hızı, exp/saat) |
| **S3** | Ağlı Mühür Taşı: monolith türleri genelleştirme, model, dalgalar, loot | Taş kesme |
| **S4** | Seyahat altyapısı + Uçuç Ağı: `travel.json`, protokol v19, harita içi ışınlama, Uçuç Tozu, 5 şömine, pencere, yeşil alev FX + ses | Şöminelerle tur |
| **S5** | Anahtar: çizme eşyası, yere koyma varlığı, tutunma, parti filtresi, toplu transfer, girdap FX | 2 istemci aynı partide birlikte ışınlanma |
| **S6** | (ops.) Kraliçe'nin Odası: instanced, Kraliçe Mührü, Matriarch modeliyle boss | — |
| **S7** | (ops.) Kaybolan Dolaplar + Tek Gözlü Cadı geçidi | — |
| **Son** | Mağara propları (Hunyuan) yerleştirme, `dev.ps1 ready -Full`, `multiplayer_sim`'e Anahtar senaryosu, iki repoyu main'e commit + push | — |

Test politikası: yeni regresyon testi yok; doğrulama oyunda (`--solo --test-char=…`, yerel sunucu + 2 istemci) +
mevcut import kontrolü ve `multiplayer_sim`.

## 7. Riskler

| Risk | Önlem |
|---|---|
| Mağara iGPU'da ağır (çok ışık, sis, prop) | Gölgesiz ışık sınırı, prop'lar MultiMesh, low preset'te sis/volumetrik kapalı, chunk LOD |
| 64 kişilik paylaşımlı haritada ~200 mob sunucu tick'i | Mevcut ilgi ızgarası + dormant encounter kuralı; mob başı ~0.115 MB → ~25 MB |
| Hunyuan 504 / 40k tri | Meshy 7.1 yedeği; decimate + bake zaten akışta |
| Örümcek rig'i yeni mesh'e oturmazsa | Acromantula rig + voxel proxy ağırlık; olmazsa Meshy multi-animation |
| Anahtar toplu transferde bir üye yüklemede gecikirse | Transfer kişi başı ayrı token (mevcut sistem); iniş halkası sunucuda önceden ayrılır |
| Harita içi ışınlama istemci tahminiyle çakışır | Sunucu zorla konum + sahip tahminine düzeltme (mevcut `sim_push` deseni) |

## 8. Kararlar (varsayılanlar)

1. **İsim:** Kara Ağ Mağaraları (*Blackweb Caverns*).
2. **Harita tipi:** paylaşımlı kasılma haritası; boss odası ayrı ve instanced (S6).
3. **Giriş:** Lanetli Mahzen merdiveni (fiziksel) + şömine (kamp) + Anahtar.
4. **Uçuç Tozu:** tüketilir, satıcı 2.500 galleon + drop; sadece daha önce ziyaret edilen şöminelere gidilir.
5. **Anahtar:** tek kullanımlık, 10 sn geri sayım, sadece parti; satıcı 10.000 galleon + nadir drop.
6. **Dolap / Cadı geçidi:** S7'de (ilk turda değil).

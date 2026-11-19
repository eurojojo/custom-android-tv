# Thomson 240G (Google TV)

Productnaam `SEI700BTHSG`, Android 14, Google TV-launcher (`com.google.android.apps.tv.launcherx`). Meegeleverd: KPN TV+-app.
Logboek met elke wijziging en hoe die terug te draaien: [`TERUGDRAAIEN.md`](TERUGDRAAIEN.md).

## Toegang
- ADB over het netwerk: `adb connect <box-ip>:5555` (eenmalig op de TV bevestigen met "Altijd toestaan"). Na een herstart of na sommige ingrepen kan ADB-foutopsporing weer uit staan (Ontwikkelaarsopties).
- Het draadloze-foutopsporingsadres met koppelcode (andere poort) is niet nodig.

## Wat werkt
1. **Projectivy Launcher als startscherm, zonder de Google-launcher uit te zetten.** Alleen via de toegankelijkheidsservice van Projectivy:
   `settings put secure enabled_accessibility_services com.spocky.projengmenu/com.spocky.projengmenu.services.ProjectivyAccessibilityService` en `settings put secure accessibility_enabled 1`.
   Een force-stop van Projectivy zet de service weer uit; opnieuw aanzetten en Projectivy starten.
2. **Projectivy moet `android.permission.READ_TV_LISTINGS` hebben** (`pm grant com.spocky.projengmenu android.permission.READ_TV_LISTINGS`). Zonder deze permissie, die standaard in de eerste-keer-wizard kan worden geweigerd, blijven alle kanalen en "Verder kijken" leeg.
3. **TV uit = box in stand-by**: staat bij de TV (Philips, EasyLink) "apparaten automatisch uitschakelen" aan. Dan start Projectivy "autostart bij ontwaken" = KPN TV+.
4. **Box wekt de TV niet meer zelf:** `cmd hdmi_control cec_setting set tv_wake_on_one_touch_play 0`.
5. **Watch Next / "Verder kijken"** van een eigen app verschijnt in Projectivy (zie `apps/tvrows`).

## Wat NIET werkt (niet opnieuw proberen)
- **Google-launcher (`launcherx`) uitzetten met `pm disable-user`:** het Google-herstelscherm (`setupwraith/.RecoveryActivity`) gaat dan in een lus draaien.
- **Dat herstelscherm of de hele setup-wizard-app (`setupwraith`) uitzetten:** losse component mag niet via adb; de hele app uitzetten laat de box van het netwerk vallen (wifi-wachtwoord moet opnieuw ingevoerd worden, ADB staat uit).
- **Eigen "preview channels"** (rijen als "Test: nieuwe films") zijn niet browsable: `AddChannelActivity` van Google geeft direct `RESULT_CANCELED`, en browsable zetten via adb mag niet (`SecurityException`). Watch Next heeft dat niet nodig.
- **KPN TV+ laatste zender:** de app heeft die instelling niet en kent geen openbare deeplink per zender.
- `content query` op de TV-provider vanuit de shell toont niets (geen rechten), dus daar niet op controleren.

## Handig
- Menu-toets (`input keyevent 82`) opent het zijpaneel van Projectivy; navigeren met adb is lastig (focus springt). Laat de gebruiker liever zelf met de afstandsbediening klikken.
- Een eigen app bouwen zonder Gradle: zie `apps/tvrows/build.ps1` (aapt2, javac, d8, zipalign, apksigner; Android-platform 34 nodig).

## NextPVR-opnames: container `tvfeed` op de NextPVR-server
`tvfeed/` (Dockerfile + compose) draait als container naast NextPVR (`~/services/tvfeed/`, poort 8871, geheugen 256 MB). Elke 10 minuten logt hij in op NextPVR (PIN in `secrets.json`, chmod 600, niet in de repo), haalt de 20 nieuwste klare opnames op en maakt van de 12 nieuwste een 16:9-kaart (JPEG, Pillow) in `out/cards/<id>.jpg`, plus `out/recordings.json`. Beide worden alleen-lezen geserveerd op `http://<nextpvr-host>:8871/`.
Plaatje per opname, op volgorde van voorkeur: (a) bestand naast de opname (zelfde naam, of folder/poster/fanart); (b) de EPG-artwork-URL die NextPVR bewaart (`DeferredArtwork` in `SCHEDULED_RECORDING.event_details` in `npvr.db3`), eenmalig gedownload en gecachet; (c) NextPVR's show-artwork (`config/media/shows/<Titel>.fanart|landscape.jpg`); (d) kleurverloop met zenderlogo. Staande posters komen links met tekst rechts, liggende beelden vullen de kaart.
Mounts (alleen-lezen): `npvr.db3`, `config/media`, de opnamemap. De NextPVR-API: `session.initiate` → `session.login` (md5 van `:` + md5(pin) + `:` + salt) → `recording.list&filter=ready`; zonder `filter=ready` komen alleen geplande opnames. NextPVR geeft zijn artwork niet via de API (`recording.artwork` → 404).
Het eerdere HA-script (`ha/`) is vervangen door deze container; de bestanden op de HA-Pi zijn op 2026-11-18 verwijderd. `ha/` staat alleen nog als voorbeeld in de repo.

## Volgende stappen
- Echte kaarten in plaats van proefkaarten publiceren (laatste opnames, nieuwe films/series, laatst gekeken) vanuit Home Assistant.

## tvfeed v2: volgorde en nieuwe films/series
De rij ("Volgende bekijken") wordt in de container samengesteld: (1) opnames waar je mee bezig bent (2–95% gekeken, uit NextPVR's `PLAYBACK_POSITION`), laatst bekeken eerst, met voortgangsbalk; (2) de 4 nieuwste nog niet bekeken opnames; (3) om en om de nieuwste afleveringen en films uit de videobibliotheek (bestandsscan van de mappen uit `library.json`, op wijzigingstijd, elk uur, alleen-lezen mounts); (4) de rest. Uitgekeken opnames (≥95%) komen er niet in. Posters voor films en series komen van OMDb (titel + jaar uit de mapnaam, eenmalig gedownload en gecachet; sleutel in `secrets.json`), anders een kleurverloop.
Let op: Projectivy cachet de rij; na een wijziging in de volgorde of in oude kaarten helpt het om Projectivy te herstarten (`am force-stop com.spocky.projengmenu`, daarna de toegankelijkheidsservice opnieuw aanzetten en Projectivy starten).

## Ontwikkelstand (TV mag uit)
`svc power stayon true` en HDMI-CEC uit (`cmd hdmi_control cec_setting set hdmi_cec_enabled 0`) houden de box wakker, ook als de TV uit gaat. Zet CEC weer aan (`... 1`) voor normaal gebruik.

## Eigen rijen (preview channels) werken in Projectivy
Eerder bleken eigen kanalen niet te werken omdat Projectivy geen `READ_TV_LISTINGS` had. Met die permissie toont Projectivy de kanalen van de app onder `Menu → Kanalen bewerken → <appnaam>` (daar staat per kanaal een schakelaar **Zichtbaar**, standaard uit). De app maakt vier kanalen: `Verder kijken`, `Nieuwe opnames`, `Nieuwe series`, `Nieuwe films`. Het systeemvenster van Google om een kanaal "aan het startscherm toe te voegen" is niet nodig. Meerdere rijen = meerdere kanalen; Watch Next blijft één gedeelde rij. Premium is hier niet voor nodig (bevestigd: Premium = eigen achtergronden, kaartpictogrammen, lettertypen, ouderlijk toezicht).
Via adb is het menu lastig te bedienen (focus springt, per ongeluk zijn de instellingen van een andere app geopend); laat de gebruiker de schakelaars zelf zetten.

## Afspelen (v0.7)
`tvfeed` serveert de bestanden die nu in de lijst staan alleen-lezen op `http://<host>:8871/media/<id>` (met HTTP-Range, zodat spoelen werkt; onbekende id's geven 404, er is geen map-browsing). De app start die URL met `ACTION_VIEW` (`video/*`) in VLC (`org.videolan.vlc`) of een andere speler, en geeft bij "Verder kijken" de laatste positie mee (`position`, ms). Is er geen speler, dan toont de app het infoscherm. Op de Thomson stond bij oplevering nog geen speler: installeer VLC uit de Play Store.
Rijen: `Verder kijken` = bezig (2–95%); `Nieuwe opnames` = de 8 nieuwste niet-uitgekeken opnames op opnamedatum (dubbel met "Verder kijken" mag); `Nieuwe series/films` op toevoegdatum.

## Posters: OMDb en TheTVDB
Volgorde: sidecar → EPG-URL → show-artwork (opnames) en OMDb → TheTVDB (bibliotheek). Voor TheTVDB zet je `tvdb_key` (en evt. `tvdb_pin`) in `secrets.json`; de zoekfunctie gebruikt ook aliassen (bijv. "Plur1bus"/"Pluribus").

## Aanbevolen-achtergrond (Projectivy-wallpaperplug-in, v0.8)
De app bevat `HeroProviderService`, een Projectivy-wallpaperprovider (actie `tv.projectivy.plugin.WALLPAPER_PROVIDER`, `apiVersion` 1). De API zit als AIDL + twee kleine Java-parcelables in de app (`aidl/`, `src/tv/projectivy/...`), gebouwd met `aidl.exe` uit de build-tools (zie `build.ps1`); de parcelvolgorde is gelijk aan Projectivy's Kotlin-`@Parcelize`-klassen (`Event` moet volledig gelezen worden, anders weigert de gegenereerde AIDL-code de parcel). `tvfeed` rendert elke 10 min drie 1920×1080-beelden (nummer 1 van Nieuwe opnames, Nieuwe series, Nieuwe films; titel linksboven, donker onderaan) naar `hero/` + `hero.json`; de plug-in levert die als IMAGE-wallpapers, Projectivy wisselt ze. Kies in Projectivy de plug-in als wallpaper-bron (Premium vereist voor eigen wallpapers).
De app publiceert zelf geen Watch Next meer: de systeemrij "Volgende bekijken" blijft voor Netflix/Disney+/Prime enz.

## Kodi-koppeling (alleen lezen)
`tvfeed` vraagt elke ±4 minuten de Kodi's in `secrets.json` (`"kodis": {naam: {host, user, password}}`, JSON-RPC op poort 8080) wat je bezig bent: series met `0 < gezien < totaal` waarvan je de afgelopen 8 maanden keek (daarvan de eerstvolgende niet geziene aflevering) en films met een hervatpunt (`inprogress`). Is een Kodi uit, dan blijft de laatst bekende stand uit `out/kodi_state.json` staan; per titel telt de meest recente. Kodi-bestanden (`smb://server/<share>/…`) worden volgens `kodi_shares` in `library.json` naar de eigen mounts (`/lib/<n>`) vertaald en via de container afgespeeld. Ze komen in **Verder kijken**, samen met opnames waar je mee bezig bent, op laatst gekeken. **Nieuwe series** laat series die al in Verder kijken staan niet meer zien.

## Configuratie van tvfeed (niets hiervan staat in de repo)
In de map van de container staan drie lokale bestanden, naast `docker-compose.yml`:
- `.env`: adressen en mappen (zie `.env.example`): NextPVR-host, NextPVR-configmap, opnamemap en tot vier mediamappen (`MEDIA_1`…`MEDIA_4`, alleen-lezen gemount als `/lib/1`…`/lib/4`).
- `library.json`: welke submappen films en series bevatten en hoe Kodi-shares op de mounts passen (zie `library.example.json`).
- `secrets.json`: NextPVR-PIN en API-sleutels (OMDb, TheTVDB), en de Kodi-webgegevens (`chmod 600`).
De app krijgt het adres van tvfeed bij het bouwen: `.\build.ps1 -FeedUrl http://<server>:8871/recordings.json`.

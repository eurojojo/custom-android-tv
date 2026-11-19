package nl.joost.tvrows;

import android.content.ContentUris;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.media.tv.TvContract;
import android.net.Uri;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * Haalt de lijst met laatste NextPVR-opnames bij Home Assistant op en zet ze als
 * "Watch Next"-kaarten op het startscherm (Projectivy toont die onder "Volgende bekijken").
 */
public final class Publisher {
    /** Lijst en kaarten die de tvfeed-container op de NextPVR-server klaarzet (map tvfeed/). */
    /** Adres van tvfeed, ingesteld bij het bouwen (build.ps1 -FeedUrl). */
    public static String feedUrl(Context c) { return c.getString(R.string.feed_url); }
    public static String feedBase(Context c) { String u = feedUrl(c); return u.substring(0, u.lastIndexOf('/') + 1); }
    private static final int MAX_CARDS = 20;
    private static final int[] POSTERS = {R.drawable.poster1, R.drawable.poster2, R.drawable.poster3};

    private Publisher() {}

    /** Haalt het lijstje op en vervangt onze Watch Next-kaarten. Draai dit NIET op de hoofdthread. */
    public static synchronized String refresh(Context c) {
        try {
            JSONArray list = fetch(c).getJSONArray("recordings");
            String kanalen = publishChannels(c, list);
            deleteOurWatchNext(c);
            return kanalen; // geen eigen Watch Next meer: de systeemrij "Volgende bekijken" blijft voor de streamingdiensten
        } catch (Throwable t) {
            android.util.Log.e("tvrows", "verversen mislukt", t);
            return "Mislukt: " + t;
        }
    }

    // ---- eigen rijen (preview channels): één per soort ----
    private static final String[][] KANALEN = {
            {"bezig", "Verder kijken"}, {"opname", "Nieuwe opnames"},
            {"aflevering", "Nieuwe series"}, {"film", "Nieuwe films"}};

    private static String publishChannels(Context c, JSONArray list) {
        StringBuilder sb = new StringBuilder();
        for (String[] k : KANALEN) {
            try {
                long channelId = findChannel(c, k[0]);
                if (channelId < 0) {
                    ContentValues v = new ContentValues();
                    v.put(TvContract.Channels.COLUMN_TYPE, TvContract.Channels.TYPE_PREVIEW);
                    v.put(TvContract.Channels.COLUMN_DISPLAY_NAME, k[1]);
                    v.put(TvContract.Channels.COLUMN_INTERNAL_PROVIDER_ID, k[0]);
                    v.put(TvContract.Channels.COLUMN_APP_LINK_INTENT_URI, detailRoot(c));
                    Uri u = c.getContentResolver().insert(TvContract.Channels.CONTENT_URI, v);
                    if (u == null) { sb.append(k[1]).append(": niet aangemaakt; "); continue; }
                    channelId = ContentUris.parseId(u);
                }
                try { // naam bijwerken als die veranderd is
                    ContentValues nm = new ContentValues();
                    nm.put(TvContract.Channels.COLUMN_DISPLAY_NAME, k[1]);
                    c.getContentResolver().update(TvContract.buildChannelUri(channelId), nm, null, null);
                } catch (Throwable ignored) { }
                clearChannel(c, channelId);
                int n = 0;
                // Kies de kaarten voor deze rij:
                //  - "Verder kijken": alles waar je mee bezig bent (opnames, films, series), laatst bekeken eerst;
                //  - "Nieuwe opnames": opnames op opnamedatum, ook als je al begonnen bent (dubbel mag);
                //  - "Nieuwe series/films": nieuw toegevoegd, nog niet begonnen.
                java.util.ArrayList<JSONObject> sel = new java.util.ArrayList<>();
                for (int i = 0; i < list.length(); i++) {
                    JSONObject r = list.getJSONObject(i);
                    String state = r.optString("state", "nieuw");
                    if ("klaar".equals(state)) continue;
                    String kind = r.optString("kind", "opname");
                    boolean inKanaal;
                    if ("bezig".equals(k[0])) inKanaal = "bezig".equals(state);
                    else if ("opname".equals(k[0])) inKanaal = "opname".equals(kind);
                    else inKanaal = kind.equals(k[0]) && "nieuw".equals(state);
                    if (inKanaal) sel.add(r);
                }
                final String sleutel = k[0];
                java.util.Collections.sort(sel, new java.util.Comparator<JSONObject>() {
                    @Override public int compare(JSONObject a, JSONObject b) {
                        long x = "bezig".equals(sleutel) ? a.optLong("last") : "opname".equals(sleutel) ? a.optLong("start") : 0;
                        long y = "bezig".equals(sleutel) ? b.optLong("last") : "opname".equals(sleutel) ? b.optLong("start") : 0;
                        return Long.compare(y, x); // nieuwste/laatst bekeken eerst; gelijk = volgorde van de lijst blijft
                    }
                });
                for (int i = 0; i < sel.size(); i++) {
                    JSONObject r = sel.get(i);
                    String state = r.optString("state", "nieuw");
                    ContentValues p = new ContentValues();
                    p.put(TvContract.PreviewPrograms.COLUMN_CHANNEL_ID, channelId);
                    p.put(TvContract.PreviewPrograms.COLUMN_TYPE, TvContract.PreviewPrograms.TYPE_MOVIE);
                    p.put(TvContract.PreviewPrograms.COLUMN_TITLE, r.optString("title"));
                    p.put(TvContract.PreviewPrograms.COLUMN_SHORT_DESCRIPTION,
                            r.optString("channel") + " · " + shortDate(r.optLong("start")));
                    String card = r.isNull("card") ? "" : r.optString("card");
                    if (!card.isEmpty()) {
                        p.put(TvContract.PreviewPrograms.COLUMN_POSTER_ART_URI, feedBase(c) + card);
                        p.put(TvContract.PreviewPrograms.COLUMN_POSTER_ART_ASPECT_RATIO, TvContract.PreviewPrograms.ASPECT_RATIO_16_9);
                    }
                    if ("bezig".equals(state)) {
                        p.put(TvContract.PreviewPrograms.COLUMN_DURATION_MILLIS, r.optLong("watch_duration") * 1000L);
                        p.put(TvContract.PreviewPrograms.COLUMN_LAST_PLAYBACK_POSITION_MILLIS, r.optLong("position") * 1000L);
                    }
                    p.put(TvContract.PreviewPrograms.COLUMN_INTENT_URI, detailIntent(c, r));
                    p.put(TvContract.PreviewPrograms.COLUMN_WEIGHT, 1000 - i);
                    p.put(TvContract.PreviewPrograms.COLUMN_INTERNAL_PROVIDER_ID, k[0] + "-" + r.optString("id"));
                    if (c.getContentResolver().insert(TvContract.PreviewPrograms.CONTENT_URI, p) != null) n++;
                }
                sb.append(k[1]).append(" (kanaal ").append(channelId).append("): ").append(n).append("; ");
            } catch (Throwable t) {
                android.util.Log.e("tvrows", "kanaal " + k[1], t);
                sb.append(k[1]).append(": fout; ");
            }
        }
        android.util.Log.i("tvrows", "kanalen: " + sb);
        return sb.toString();
    }

    private static long findChannel(Context c, String internalId) {
        try (Cursor cur = c.getContentResolver().query(TvContract.Channels.CONTENT_URI,
                new String[]{TvContract.Channels._ID, TvContract.Channels.COLUMN_INTERNAL_PROVIDER_ID}, null, null, null)) {
            while (cur != null && cur.moveToNext()) {
                if (internalId.equals(cur.getString(1))) return cur.getLong(0);
            }
        }
        return -1;
    }

    private static void clearChannel(Context c, long channelId) {
        java.util.ArrayList<Long> ids = new java.util.ArrayList<>();
        try (Cursor cur = c.getContentResolver().query(TvContract.buildPreviewProgramsUriForChannel(channelId),
                new String[]{TvContract.PreviewPrograms._ID}, null, null, null)) {
            while (cur != null && cur.moveToNext()) ids.add(cur.getLong(0));
        }
        for (long id : ids) {
            c.getContentResolver().delete(TvContract.buildPreviewProgramUri(id), null, null);
        }
    }

    private static String detailRoot(Context c) {
        return new Intent(c, MainActivity.class).toUri(Intent.URI_INTENT_SCHEME);
    }

    private static JSONObject fetch(Context c) throws Exception {
        return fetchJson(feedUrl(c));
    }

    public static JSONObject fetchJson(String url) throws Exception {
        HttpURLConnection h = (HttpURLConnection) new URL(url).openConnection();
        h.setConnectTimeout(8000);
        h.setReadTimeout(8000);
        try (BufferedReader br = new BufferedReader(new InputStreamReader(h.getInputStream(), "UTF-8"))) {
            StringBuilder sb = new StringBuilder();
            for (String l; (l = br.readLine()) != null; ) sb.append(l).append('\n');
            return new JSONObject(sb.toString());
        } finally {
            h.disconnect();
        }
    }

    /** Verwijdert onze eerdere kaarten één voor één (een delete met filter mag niet, SecurityException). */
    private static void deleteOurWatchNext(Context c) {
        java.util.ArrayList<Long> ids = new java.util.ArrayList<>();
        try (Cursor cur = c.getContentResolver().query(TvContract.WatchNextPrograms.CONTENT_URI,
                new String[]{TvContract.WatchNextPrograms._ID}, null, null, null)) {
            while (cur != null && cur.moveToNext()) ids.add(cur.getLong(0));
        } catch (Throwable t) {
            android.util.Log.e("tvrows", "lezen eigen kaarten mislukt", t);
        }
        int weg = 0;
        for (long id : ids) {
            try {
                weg += c.getContentResolver().delete(TvContract.buildWatchNextProgramUri(id), null, null);
            } catch (Throwable t) {
                android.util.Log.e("tvrows", "verwijderen mislukt " + id, t);
            }
        }
        android.util.Log.i("tvrows", "eigen kaarten gevonden: " + ids.size() + ", verwijderd: " + weg);
    }

    /** De niet-browsable proefkanalen van de eerdere testversie opruimen. */
    private static void removeOldTestChannels(Context c) {
        try (Cursor cur = c.getContentResolver().query(TvContract.Channels.CONTENT_URI,
                new String[]{TvContract.Channels._ID}, null, null, null)) {
            while (cur != null && cur.moveToNext()) {
                c.getContentResolver().delete(ContentUris.withAppendedId(TvContract.Channels.CONTENT_URI, cur.getLong(0)), null, null);
            }
        } catch (Throwable ignored) { }
    }

    private static String detailIntent(Context c, JSONObject r) {
        Intent i = new Intent(c, MainActivity.class);
        i.putExtra("soort", "opname");
        i.putExtra("titel", r.optString("title"));
        i.putExtra("kanaal", r.optString("channel"));
        i.putExtra("start", r.optLong("start"));
        i.putExtra("duur", r.optLong("duration"));
        i.putExtra("omschrijving", r.optString("description"));
        i.putExtra("id", r.optString("id"));
        String play = r.optString("play", "");
        if (!play.isEmpty()) i.putExtra("play", feedBase(c) + play);
        i.putExtra("positie", r.optLong("position", 0));
        i.putExtra("kind", r.optString("kind", "opname"));
        return i.toUri(Intent.URI_INTENT_SCHEME);
    }

    static String shortDate(long epochSeconds) {
        return new java.text.SimpleDateFormat("EEE d MMM HH:mm", new java.util.Locale("nl", "NL"))
                .format(new java.util.Date(epochSeconds * 1000L));
    }
}



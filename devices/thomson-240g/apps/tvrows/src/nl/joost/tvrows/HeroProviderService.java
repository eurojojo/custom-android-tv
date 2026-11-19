package nl.joost.tvrows;

import android.app.Service;
import android.content.Intent;
import android.os.IBinder;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

import tv.projectivy.plugin.wallpaperprovider.api.Event;
import tv.projectivy.plugin.wallpaperprovider.api.IWallpaperProviderService;
import tv.projectivy.plugin.wallpaperprovider.api.Wallpaper;

/**
 * Projectivy-wallpaperplug-in: levert als achtergrond de "Aanbevolen"-beelden (nummer 1 van Nieuwe opnames,
 * Nieuwe series en Nieuwe films) die de tvfeed-container klaarzet. Projectivy wisselt ze om en om.
 */
public class HeroProviderService extends Service {
    private static final String TAG = "tvrows-hero";

    @Override public IBinder onBind(Intent intent) { return binder; }

    private final IWallpaperProviderService.Stub binder = new IWallpaperProviderService.Stub() {
        @Override public List<Wallpaper> getWallpapers(Event event) {
            List<Wallpaper> out = new ArrayList<>();
            if (event == null || event.eventType != 1) return out; // alleen op TimeElapsed een lijst geven
            try {
                String base = Publisher.feedBase(HeroProviderService.this);
                JSONArray items = Publisher.fetchJson(base + "hero.json").getJSONArray("items");
                for (int i = 0; i < items.length(); i++) {
                    JSONObject h = items.getJSONObject(i);
                    out.add(new Wallpaper(base + h.getString("uri"), Wallpaper.TYPE_IMAGE, Wallpaper.MODE_CROP,
                            h.optString("title"), h.optString("label"), null, null));
                }
                Log.i(TAG, "wallpapers: " + out.size());
            } catch (Throwable t) {
                Log.e(TAG, "hero.json ophalen mislukt", t);
            }
            return out;
        }

        @Override public String getPreferences() { return ""; }
        @Override public void setPreferences(String params) { }
    };
}


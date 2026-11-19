package nl.joost.tvrows;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.TextView;

/**
 * Zonder extra's: ververst de kaarten en toont het resultaat.
 * Met extra's (kaart aangeklikt): toont de gegevens van de opname.
 */
public class MainActivity extends Activity {
    private TextView tv;

    /** Start de stream in VLC (of een andere speler); hervat op de plek waar je gebleven was. */
    private boolean speel(String url) {
        android.net.Uri uri = android.net.Uri.parse(url);
        long posMs = getIntent().getLongExtra("positie", 0) * 1000L;
        String[] pakketten = {"org.videolan.vlc", null};
        for (String pkg : pakketten) {
            android.content.Intent i = new android.content.Intent(android.content.Intent.ACTION_VIEW);
            i.setDataAndType(uri, "video/*");
            if (pkg != null) i.setPackage(pkg);
            i.putExtra("title", getIntent().getStringExtra("titel"));
            if (posMs > 0) i.putExtra("position", posMs);
            else i.putExtra("from_start", true);
            try {
                startActivity(i);
                return true;
            } catch (android.content.ActivityNotFoundException e) {
                // volgende proberen
            }
        }
        return false;
    }

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        tv = new TextView(this);
        tv.setTextSize(26);
        tv.setTextColor(Color.WHITE);
        tv.setBackgroundColor(Color.parseColor("#102030"));
        tv.setGravity(Gravity.CENTER);
        tv.setPadding(120, 60, 120, 60);
        setContentView(tv);
        verwerk();
    }

    /** Een kaart die aangeklikt wordt terwijl de app al open staat komt hier binnen (niet in onCreate). */
    @Override protected void onNewIntent(android.content.Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        verwerk();
    }

    private void verwerk() {
        if ("opname".equals(getIntent().getStringExtra("soort"))) {
            String play = getIntent().getStringExtra("play");
            if (play != null && speel(play)) {
                finish();
                return;
            }
            long dur = getIntent().getLongExtra("duur", 0) / 60;
            tv.setText(getIntent().getStringExtra("titel")
                    + "\n\n" + getIntent().getStringExtra("kanaal")
                    + " · " + Publisher.shortDate(getIntent().getLongExtra("start", 0))
                    + (dur > 0 ? " · " + dur + " min" : "")
                    + "\n\n" + getIntent().getStringExtra("omschrijving")
                    + "\n\nGeen videospeler gevonden op deze box. Installeer VLC (Play Store) om af te spelen.");
            return;
        }
        FeedJobService.schedule(this);
        tv.setText("Opnames ophalen…");
        new Thread(new Runnable() {
            @Override public void run() {
                final String res = Publisher.refresh(MainActivity.this);
                runOnUiThread(new Runnable() {
                    @Override public void run() { tv.setText(res); }
                });
            }
        }).start();
    }
}

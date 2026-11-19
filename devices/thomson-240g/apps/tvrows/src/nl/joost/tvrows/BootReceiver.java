package nl.joost.tvrows;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class BootReceiver extends BroadcastReceiver {
    @Override public void onReceive(final Context context, Intent intent) {
        FeedJobService.schedule(context);
        final PendingResult pr = goAsync();
        new Thread(new Runnable() {
            @Override public void run() {
                try { Publisher.refresh(context); } finally { pr.finish(); }
            }
        }).start();
    }
}

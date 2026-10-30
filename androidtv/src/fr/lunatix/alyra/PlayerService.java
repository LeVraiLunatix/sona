package fr.lunatix.alyra;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

import fr.lunatix.alyra.Models.Track;

/** Garde le processus (et donc la musique) vivant quand l'appli n'est plus au premier plan. */
public class PlayerService extends Service implements Player.Listener {
    private static final String CHANNEL = "alyra-lecture";

    @Override public void onCreate() {
        super.onCreate();
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "Lecture", NotificationManager.IMPORTANCE_LOW);
            getSystemService(NotificationManager.class).createNotificationChannel(ch);
        }
        Player.I.addListener(this);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        refresh();
        return START_NOT_STICKY;
    }

    @Override public void onChange() { refresh(); }

    private void refresh() {
        Track t = Player.I.current();
        int st = Player.I.state();
        boolean stop = t == null || st == Player.IDLE || st == Player.ERROR;
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        b.setSmallIcon(android.R.drawable.ic_media_play)
                .setContentTitle(t == null || t.title == null ? "Alyra" : t.title)
                .setContentText(t == null || t.artist == null ? "" : t.artist)
                .setContentIntent(open)
                .setOngoing(st == Player.PLAYING)
                .setStyle(new Notification.MediaStyle().setMediaSession(Player.I.sessionToken()));
        startForeground(1, b.build()); // obligatoire apres startForegroundService, meme si on s'arrete aussitot
        if (stop) {
            stopForeground(true);
            stopSelf();
        } else if (st == Player.PAUSED) {
            stopForeground(false);
        }
    }

    @Override public void onDestroy() {
        Player.I.removeListener(this);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}

package fr.sona.quest

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Calendar

/** Réveil musical : à l'heure choisie, ton mix du jour démarre doucement (le volume monte en 90 s). */
object Alarm {
    private fun pending(context: Context, flags: Int = 0): PendingIntent = PendingIntent.getBroadcast(
        context, 7, Intent(context, AlarmReceiver::class.java),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT or flags,
    )

    /** Programme (ou annule) la prochaine sonnerie d'après les réglages. */
    fun schedule(context: Context) {
        val settings = Hub.settings
        val alarms = context.getSystemService(AlarmManager::class.java) ?: return
        val trigger = pending(context)
        if (!settings.alarmOn) {
            alarms.cancel(trigger)
            return
        }
        val at = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, settings.alarmHour)
            set(Calendar.MINUTE, settings.alarmMinute)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
            if (timeInMillis <= System.currentTimeMillis()) add(Calendar.DAY_OF_YEAR, 1)
        }
        val show = PendingIntent.getActivity(
            context, 8, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
        )
        // Un réveil « horloge » : exact sans autorisation spéciale, même en veille.
        alarms.setAlarmClock(AlarmManager.AlarmClockInfo(at.timeInMillis, show), trigger)
    }

    suspend fun fire() {
        Hub.ensureService()
        val mixes = withContext(Dispatchers.IO) { runCatching { Hub.api.mixes() }.getOrNull() } ?: return
        val mix = mixes.firstOrNull { it.id == "daily" && it.tracks.isNotEmpty() } ?: mixes.firstOrNull { it.tracks.isNotEmpty() } ?: return
        Sound.alarmGain = 0.05f
        Sound.apply()
        Hub.playQueue(mix.tracks, 0, "Réveil · ${mix.title}")
        for (step in 1..30) {
            delay(3000)
            Sound.alarmGain = (0.05f + 0.95f * step / 30f).coerceAtMost(1f)
            Sound.apply()
        }
        Sound.alarmGain = 1f
        Sound.apply()
    }
}

class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        Hub.scope.launch { Alarm.fire() }
        // Demain à la même heure.
        Alarm.schedule(context)
    }
}

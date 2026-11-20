package fr.sona.quest

import android.app.Application

class SonaApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Hub.init(this)
    }
}

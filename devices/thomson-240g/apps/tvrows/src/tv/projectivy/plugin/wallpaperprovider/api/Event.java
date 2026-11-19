package tv.projectivy.plugin.wallpaperprovider.api;

import android.os.Parcel;
import android.os.Parcelable;

/**
 * Leest de gebeurtenis van Projectivy (alleen het type is voor ons van belang) maar verbruikt de hele
 * parcel, want de gegenereerde AIDL-code weigert restdata. Indeling = Kotlin @Parcelize van Projectivy:
 *  1 TimeElapsed: alleen het type
 *  2 NowPlayingChanged: type, isPlaying(int), title, artist, album, iconUri
 *  4 CardFocused: type, lightColor, darkColor, title, packageName
 *  8 ProgramCardFocused: type, title, type? (vlag + int), iconUri, iconAspectRatio
 * 16 LauncherIdleModeChanged: type, isIdle(int)
 */
public final class Event implements Parcelable {
    public final int eventType;

    public Event(int eventType) { this.eventType = eventType; }

    @Override public void writeToParcel(Parcel p, int flags) { p.writeInt(eventType); }
    @Override public int describeContents() { return 0; }

    public static final Parcelable.Creator<Event> CREATOR = new Parcelable.Creator<Event>() {
        @Override public Event createFromParcel(Parcel p) {
            int type = p.readInt();
            switch (type) {
                // het eerste veld (eventType) is hierboven al gelezen
                case 2: p.readInt(); p.readString(); p.readString(); p.readString(); p.readString(); break;
                case 4: p.readInt(); p.readInt(); p.readString(); p.readString(); break;
                case 8: p.readString(); if (p.readInt() != 0) p.readInt(); p.readString(); p.readInt(); break;
                case 16: p.readInt(); break;
                default: break; // 1 = TimeElapsed (object): niets meer
            }
            return new Event(type);
        }
        @Override public Event[] newArray(int n) { return new Event[n]; }
    };
}

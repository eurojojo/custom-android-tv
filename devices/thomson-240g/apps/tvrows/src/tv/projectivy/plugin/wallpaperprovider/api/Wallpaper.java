package tv.projectivy.plugin.wallpaperprovider.api;

import android.os.Parcel;
import android.os.Parcelable;

/** Zelfde parcel-indeling als de Kotlin-klasse van Projectivy (@Parcelize): velden in deze volgorde. */
public final class Wallpaper implements Parcelable {
    public static final int TYPE_IMAGE = 0;
    public static final int MODE_CROP = 1;

    public final String uri;
    public final int type;
    public final int displayMode;
    public final String title;
    public final String source;
    public final String author;
    public final String actionUri;

    public Wallpaper(String uri, int type, int displayMode, String title, String source, String author, String actionUri) {
        this.uri = uri;
        this.type = type;
        this.displayMode = displayMode;
        this.title = title;
        this.source = source;
        this.author = author;
        this.actionUri = actionUri;
    }

    @Override public void writeToParcel(Parcel p, int flags) {
        p.writeString(uri);
        p.writeInt(type);
        p.writeInt(displayMode);
        p.writeString(title);
        p.writeString(source);
        p.writeString(author);
        p.writeString(actionUri);
    }

    @Override public int describeContents() { return 0; }

    public static final Parcelable.Creator<Wallpaper> CREATOR = new Parcelable.Creator<Wallpaper>() {
        @Override public Wallpaper createFromParcel(Parcel p) {
            return new Wallpaper(p.readString(), p.readInt(), p.readInt(), p.readString(), p.readString(), p.readString(), p.readString());
        }
        @Override public Wallpaper[] newArray(int n) { return new Wallpaper[n]; }
    };
}

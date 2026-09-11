package com.centralaguas.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.provider.Settings;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public class FcmTokenReporter {
    private static final String PREFS = "central_aguas_app";
    private static final String TOKEN_KEY = "last_fcm_token";

    public static void report(Context context, String token) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (token.equals(prefs.getString(TOKEN_KEY, ""))) return;

        new Thread(() -> {
            try {
                String androidId = Settings.Secure.getString(context.getContentResolver(), Settings.Secure.ANDROID_ID);
                JSONObject payload = new JSONObject();
                payload.put("device_id", "android-" + androidId);
                payload.put("token", token);
                payload.put("notification_permission", "granted");
                payload.put("platform", "android");

                HttpURLConnection connection = (HttpURLConnection) new URL(context.getString(R.string.fcm_token_url)).openConnection();
                connection.setRequestMethod("POST");
                connection.setRequestProperty("Content-Type", "application/json");
                connection.setDoOutput(true);
                byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(body);
                }
                int status = connection.getResponseCode();
                if (status >= 200 && status < 300) {
                    prefs.edit().putString(TOKEN_KEY, token).apply();
                }
                connection.disconnect();
            } catch (Exception ignored) {
            }
        }).start();
    }
}

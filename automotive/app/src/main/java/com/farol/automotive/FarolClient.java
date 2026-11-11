package com.farol.automotive;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import org.json.JSONObject;

final class FarolClient {
    NavigationCommand fetch() throws Exception {
        if (BuildConfig.FAROL_ENDPOINT.isEmpty() || BuildConfig.FAROL_CAR_TOKEN.isEmpty()) {
            throw new IllegalStateException("Pair Farol in local.properties first");
        }
        HttpURLConnection connection = (HttpURLConnection) new URL(BuildConfig.FAROL_ENDPOINT).openConnection();
        connection.setConnectTimeout(2500);
        connection.setReadTimeout(2500);
        connection.setRequestProperty("X-Farol-Car-Token", BuildConfig.FAROL_CAR_TOKEN);
        int status = connection.getResponseCode();
        if (status == 204) return null;
        if (status != 200) throw new IllegalStateException("Surface returned HTTP " + status);
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream()))) {
            StringBuilder body = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) body.append(line);
            return new NavigationCommand(new JSONObject(body.toString()));
        } finally {
            connection.disconnect();
        }
    }
}

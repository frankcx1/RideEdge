package com.farol.automotive;

import android.content.Intent;
import android.net.Uri;
import android.util.Log;
import androidx.annotation.NonNull;
import androidx.car.app.CarContext;
import androidx.car.app.Screen;
import androidx.car.app.model.Action;
import androidx.car.app.model.MessageTemplate;
import androidx.car.app.model.Pane;
import androidx.car.app.model.PaneTemplate;
import androidx.car.app.model.Row;
import androidx.car.app.model.Template;

final class RecommendationScreen extends Screen {
    private volatile NavigationCommand command;
    private volatile String status = "Checking the Surface...";

    RecommendationScreen(CarContext context) {
        super(context);
        refresh();
    }

    private void refresh() {
        new Thread(() -> {
            try {
                NavigationCommand fetched = new FarolClient().fetch();
                if (fetched != null && fetched.isExpired()) {
                    command = null;
                    status = "Route expired - tap REFRESH";
                } else {
                    command = fetched;
                    status = command == null ? "No current route" : "Route ready";
                }
                Log.i("FarolCar", command == null
                    ? "No navigation command available"
                    : "Received command " + command.id + " for " + command.label);
            } catch (Exception error) {
                command = null;
                status = error.getMessage() != null ? error.getMessage() : "Connection failed";
                Log.e("FarolCar", "Navigation command fetch failed", error);
            }
            invalidate();
        }, "farol-route-fetch").start();
    }

    @NonNull
    @Override
    public Template onGetTemplate() {
        NavigationCommand active = command;
        if (active != null && active.isExpired()) {
            command = null;
            active = null;
            status = "Route expired - tap REFRESH";
        }
        if (active == null) {
            return new MessageTemplate.Builder(status)
                .setTitle("Farol")
                .addAction(new Action.Builder().setTitle("REFRESH").setOnClickListener(this::refresh).build())
                .build();
        }
        String evidence = active.demoOnly ? "DEMO ROUTE - NOT DRIVER ADVICE" : "Driver confirmation required";
        Pane pane = new Pane.Builder()
            .addRow(new Row.Builder().setTitle(active.action + " - " + active.label).addText(evidence).build())
            .addAction(new Action.Builder().setTitle("NAVIGATE").setOnClickListener(this::openGoogleMaps).build())
            .addAction(new Action.Builder().setTitle("REFRESH").setOnClickListener(this::refresh).build())
            .build();
        return new PaneTemplate.Builder(pane).setTitle("Farol").build();
    }

    private void openGoogleMaps() {
        NavigationCommand active = command;
        if (active == null || active.isExpired()) {
            command = null;
            status = "Route expired - tap REFRESH";
            invalidate();
            return;
        }
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(active.navigationUri()));
        intent.setPackage("com.google.android.apps.maps");
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        if (intent.resolveActivity(getCarContext().getPackageManager()) != null) {
            getCarContext().startActivity(intent);
        }
    }
}

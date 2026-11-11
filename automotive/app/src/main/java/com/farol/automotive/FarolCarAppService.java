package com.farol.automotive;

import android.content.Intent;
import androidx.annotation.NonNull;
import androidx.car.app.CarAppService;
import androidx.car.app.Session;
import androidx.car.app.validation.HostValidator;

public final class FarolCarAppService extends CarAppService {
    @NonNull
    @Override
    public HostValidator createHostValidator() {
        // Never ship ALLOW_ALL_HOSTS_VALIDATOR in a release build.
        if (BuildConfig.DEBUG) return HostValidator.ALLOW_ALL_HOSTS_VALIDATOR;
        return new HostValidator.Builder(this).build();
    }

    @NonNull
    @Override
    public Session onCreateSession() {
        return new FarolSession();
    }

    private static final class FarolSession extends Session {
        @NonNull
        @Override
        public androidx.car.app.Screen onCreateScreen(@NonNull Intent intent) {
            return new RecommendationScreen(getCarContext());
        }
    }
}

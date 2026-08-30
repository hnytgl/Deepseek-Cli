package com.sproutspeak.kids;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONArray;
import org.json.JSONObject;
import org.vosk.Model;
import org.vosk.Recognizer;
import org.vosk.android.RecognitionListener;
import org.vosk.android.SpeechService;
import org.vosk.android.StorageService;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

public class MainActivity extends Activity implements RecognitionListener {
    private static final int REQ_MIC = 1002;
    private static final String MODEL = "deepseek-v4-flash";
    private static final String PREFS = "sproutspeak_local";
    private static final String KEY_NAME = "deepseek_api_key";

    private WebView webView;
    private SharedPreferences prefs;
    private TextToSpeech tts;
    private boolean ttsReady = false;

    private Model voskModel;
    private SpeechService speechService;
    private boolean modelReady = false;
    private boolean speechActive = false;
    private boolean pendingSpeech = false;
    private String speechTarget = "chat";
    private String lastPartial = "";

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        webView = new WebView(this);
        setContentView(webView);
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.getSettings().setAllowFileAccess(true);
        webView.getSettings().setMediaPlaybackRequiresUserGesture(false);
        webView.setWebViewClient(new WebViewClient());
        webView.addJavascriptInterface(new AppBridge(), "AndroidBridge");
        initTts();
        initOfflineSpeechModel();
        webView.loadUrl("file:///android_asset/index.html");
    }

    private void initTts() {
        tts = new TextToSpeech(this, status -> {
            if (status == TextToSpeech.SUCCESS) {
                ttsReady = true;
                tts.setLanguage(Locale.US);
                tts.setSpeechRate(0.86f);
                tts.setPitch(1.02f);
                tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                    @Override public void onStart(String utteranceId) {
                        js("window.onNativeTtsStart && window.onNativeTtsStart();");
                    }
                    @Override public void onDone(String utteranceId) {
                        js("window.onNativeTtsDone && window.onNativeTtsDone();");
                    }
                    @Override public void onError(String utteranceId) {
                        js("window.onNativeTtsDone && window.onNativeTtsDone();");
                    }
                });
            } else {
                ttsReady = false;
                js("window.onNativeTtsError && window.onNativeTtsError('系统英语朗读不可用，但仍可进行文字对话');");
            }
        });
    }

    private void initOfflineSpeechModel() {
        modelReady = false;
        js("window.onNativeSpeechState && window.onNativeSpeechState('model_loading');");
        StorageService.unpack(this, "model-en-us", "model",
                model -> {
                    voskModel = model;
                    modelReady = true;
                    js("window.onNativeSpeechState && window.onNativeSpeechState('model_ready');");
                    if (pendingSpeech) {
                        pendingSpeech = false;
                        startOfflineListening();
                    }
                },
                exception -> {
                    modelReady = false;
                    js("window.onNativeSpeechError && window.onNativeSpeechError(" + JSONObject.quote("离线英语语音模型加载失败：" + safeMessage(exception)) + ");");
                });
    }

    public class AppBridge {
        @JavascriptInterface public String saveApiKey(String key) {
            if (key == null) return "API Key 为空";
            String clean = key.replaceAll("\\s+", "").trim();
            if (clean.length() < 20) return "API Key 看起来不完整，请重新复制粘贴";
            prefs.edit().putString(KEY_NAME, clean).apply();
            return "OK";
        }

        @JavascriptInterface public boolean hasApiKey() {
            return !prefs.getString(KEY_NAME, "").trim().isEmpty();
        }

        @JavascriptInterface public void clearApiKey() {
            prefs.edit().remove(KEY_NAME).apply();
        }

        @JavascriptInterface public String modelName() { return MODEL; }
        @JavascriptInterface public boolean speechAvailable() { return modelReady; }
        @JavascriptInterface public boolean speechModelReady() { return modelReady; }
        @JavascriptInterface public boolean ttsAvailable() { return ttsReady; }
        @JavascriptInterface public String speechEngineName() { return "Vosk Offline English"; }

        @JavascriptInterface public void startSpeech(String target) {
            runOnUiThread(() -> {
                speechTarget = target == null ? "chat" : target;
                if (speechActive) {
                    stopOfflineListening();
                    return;
                }
                if (android.os.Build.VERSION.SDK_INT >= 23 && checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                    pendingSpeech = true;
                    requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_MIC);
                    return;
                }
                if (!modelReady) {
                    pendingSpeech = true;
                    js("window.onNativeSpeechState && window.onNativeSpeechState('model_loading');");
                    return;
                }
                startOfflineListening();
            });
        }

        @JavascriptInterface public void stopSpeech() {
            runOnUiThread(() -> stopOfflineListening());
        }

        @JavascriptInterface public void speak(String text) {
            runOnUiThread(() -> {
                if (speechActive) cancelOfflineListening();
                if (tts != null && ttsReady && text != null && !text.trim().isEmpty()) {
                    tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "sproutspeak_turn");
                } else {
                    js("window.onNativeTtsDone && window.onNativeTtsDone();");
                }
            });
        }

        @JavascriptInterface public void chat(String messagesJson, String requestId) {
            new Thread(() -> doDeepSeek(messagesJson, requestId)).start();
        }
    }

    private void startOfflineListening() {
        if (!modelReady || voskModel == null) {
            pendingSpeech = true;
            js("window.onNativeSpeechState && window.onNativeSpeechState('model_loading');");
            return;
        }
        if (speechActive) return;
        try {
            if (tts != null) tts.stop();
            releaseSpeechService();
            lastPartial = "";
            Recognizer recognizer = new Recognizer(voskModel, 16000.0f);
            speechService = new SpeechService(recognizer, 16000.0f);
            speechActive = true;
            js("window.onNativeSpeechState && window.onNativeSpeechState('ready');");
            speechService.startListening(this);
        } catch (IOException e) {
            speechActive = false;
            releaseSpeechService();
            js("window.onNativeSpeechError && window.onNativeSpeechError(" + JSONObject.quote("无法使用麦克风：" + safeMessage(e)) + ");");
        }
    }

    private void stopOfflineListening() {
        if (!speechActive || speechService == null) return;
        speechActive = false;
        js("window.onNativeSpeechState && window.onNativeSpeechState('processing');");
        try { speechService.stop(); } catch (Exception ignored) {}
        // onFinalResult is posted by SpeechService after stop(). Keep the service alive until callback.
    }

    private void cancelOfflineListening() {
        speechActive = false;
        if (speechService != null) {
            try { speechService.cancel(); } catch (Exception ignored) {}
        }
        releaseSpeechService();
    }

    private void releaseSpeechService() {
        if (speechService != null) {
            try { speechService.shutdown(); } catch (Exception ignored) {}
            speechService = null;
        }
    }

    private String extractField(String json, String key) {
        try { return new JSONObject(json == null ? "{}" : json).optString(key, "").trim(); }
        catch (Exception ignored) { return ""; }
    }

    @Override public void onPartialResult(String hypothesis) {
        String text = extractField(hypothesis, "partial");
        if (!text.isEmpty()) lastPartial = text;
        js("window.onNativeSpeechPartial && window.onNativeSpeechPartial(" + JSONObject.quote(speechTarget) + "," + JSONObject.quote(text) + ");");
    }

    @Override public void onResult(String hypothesis) {
        String text = extractField(hypothesis, "text");
        if (!text.isEmpty()) lastPartial = text;
        if (!text.isEmpty()) {
            js("window.onNativeSpeechPartial && window.onNativeSpeechPartial(" + JSONObject.quote(speechTarget) + "," + JSONObject.quote(text) + ");");
        }
    }

    @Override public void onFinalResult(String hypothesis) {
        speechActive = false;
        String text = extractField(hypothesis, "text");
        if (text.isEmpty()) text = lastPartial;
        lastPartial = "";
        releaseSpeechService();
        if (text == null || text.trim().isEmpty()) {
            js("window.onNativeSpeechError && window.onNativeSpeechError('没有听清，请再说一次');");
            return;
        }
        js("window.onNativeSpeech && window.onNativeSpeech(" + JSONObject.quote(speechTarget) + "," + JSONObject.quote(text.trim()) + ",-1);");
    }

    @Override public void onError(Exception exception) {
        speechActive = false;
        releaseSpeechService();
        js("window.onNativeSpeechError && window.onNativeSpeechError(" + JSONObject.quote("离线语音识别失败：" + safeMessage(exception)) + ");");
    }

    @Override public void onTimeout() {
        speechActive = false;
        releaseSpeechService();
        if (!lastPartial.trim().isEmpty()) {
            String text = lastPartial.trim();
            lastPartial = "";
            js("window.onNativeSpeech && window.onNativeSpeech(" + JSONObject.quote(speechTarget) + "," + JSONObject.quote(text) + ",-1);");
        } else {
            js("window.onNativeSpeechError && window.onNativeSpeechError('没有检测到说话声音');");
        }
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_MIC) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED && pendingSpeech) {
                if (modelReady) {
                    pendingSpeech = false;
                    startOfflineListening();
                }
            } else {
                pendingSpeech = false;
                js("window.onNativeSpeechError && window.onNativeSpeechError('需要麦克风权限才能进行口语练习');");
            }
        }
    }

    private void doDeepSeek(String messagesJson, String requestId) {
        HttpURLConnection conn = null;
        try {
            String apiKey = prefs.getString(KEY_NAME, "").trim();
            if (apiKey.isEmpty()) throw new Exception("请先在设置中保存 DeepSeek API Key");
            JSONObject body = new JSONObject();
            body.put("model", MODEL);
            body.put("messages", new JSONArray(messagesJson));
            body.put("stream", false);
            body.put("temperature", 0.7);
            URL u = new URL("https://api.deepseek.com/chat/completions");
            conn = (HttpURLConnection) u.openConnection();
            conn.setConnectTimeout(20000);
            conn.setReadTimeout(60000);
            conn.setRequestMethod("POST");
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("Authorization", "Bearer " + apiKey);
            try (OutputStream os = conn.getOutputStream()) {
                os.write(body.toString().getBytes(StandardCharsets.UTF_8));
            }
            int code = conn.getResponseCode();
            InputStream in = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
            String raw = readAll(in);
            if (code < 200 || code >= 300) {
                String msg = raw;
                try {
                    JSONObject err = new JSONObject(raw).optJSONObject("error");
                    if (err != null) msg = err.optString("message", raw);
                } catch (Exception ignored) {}
                throw new Exception("DeepSeek API " + code + ": " + msg);
            }
            JSONObject data = new JSONObject(raw);
            String content = data.getJSONArray("choices").getJSONObject(0).getJSONObject("message").optString("content", "");
            callbackChat(requestId, true, content);
        } catch (Exception e) {
            callbackChat(requestId, false, safeMessage(e));
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private String readAll(InputStream in) throws Exception {
        if (in == null) return "";
        BufferedReader br = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = br.readLine()) != null) sb.append(line).append('\n');
        return sb.toString();
    }

    private String safeMessage(Exception e) {
        return e.getMessage() == null || e.getMessage().trim().isEmpty() ? "操作失败" : e.getMessage();
    }

    private void callbackChat(String id, boolean ok, String value) {
        js("window.onAndroidChat && window.onAndroidChat(" + JSONObject.quote(id == null ? "" : id) + "," + ok + "," + JSONObject.quote(value == null ? "" : value) + ");");
    }

    private void js(String script) {
        runOnUiThread(() -> {
            if (webView != null) webView.evaluateJavascript(script, null);
        });
    }

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override protected void onDestroy() {
        cancelOfflineListening();
        if (voskModel != null) {
            try { voskModel.close(); } catch (Exception ignored) {}
            voskModel = null;
        }
        if (tts != null) { tts.stop(); tts.shutdown(); }
        if (webView != null) webView.destroy();
        super.onDestroy();
    }
}

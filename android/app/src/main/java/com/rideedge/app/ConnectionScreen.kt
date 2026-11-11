package com.rideedge.app

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
internal fun ConnectionScreen(onBack: () -> Unit, onConnected: () -> Unit) {
    // Deliberately not rememberSaveable: never put credentials in saved state.
    var key by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf<String?>(null) }
    val accessNote by RideEdgeClient.accessNote.collectAsState()
    val scope = rememberCoroutineScope()
    val preview = BuildConfig.BUILD_TYPE == "preview"
    val app = LocalContext.current.applicationContext as RideEdgeApplication
    BackHandler(onBack = onBack)
    Scaffold(containerColor = RadarBg) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).imePadding().verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)) {
            EdgeButton("← Back to RideEdge", onBack, kind = EdgeButtonKind.Link)
            EdgeHeading("Connect to workstation.", size = 30)
            HorizontalDivider(thickness = 2.dp, color = Edge.Ink)
            Text("Turn on Tailscale, then enter your RideEdge access key. The phone and Android Auto share this connection.", color = RadarMuted)
            EdgeMeta(RideEdgeConnection.origin)
            if (preview) Text("OFFLINE PREVIEW · Connecting is disabled.", color = RadarAmber)
            app.previewAccessCheck?.let { Text(it, color = RadarMint, fontSize = 13.sp) }
            OutlinedTextField(key, { key = it.take(46) }, label = { Text("Access key") }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(), enabled = !busy && !preview,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, autoCorrectEnabled = false),
                modifier = Modifier.fillMaxWidth())
            EdgeButton(if (busy) "Connecting…" else "Connect", kind = EdgeButtonKind.Primary,
                enabled = !busy && !preview && RideEdgeConnection.validKey(key.trim()), onClick = {
                busy = true; note = null
                val entered = key.trim(); key = ""
                scope.launch {
                    try {
                        withContext(Dispatchers.IO) { RideEdgeClient.connect(entered) }
                        note = "Connected. Your key is saved securely on this phone."
                        onConnected()
                    } catch (cancel: CancellationException) { throw cancel }
                    catch (error: Exception) {
                        note = if (error is AccessRequiredException) error.message
                            else "Could not connect. Check Tailscale, the access key and workstation."
                    } finally { busy = false }
                }
            })
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            (note ?: accessNote)?.let { EdgeCaveat(it) }
            Text("Create or replace a key in an interactive terminal on workstation with: python -m farol.access issue", color = RadarMuted, fontSize = 13.sp)
            Text("Replacing the key disconnects clients using the old one. No key is bundled in the app or copied from the clipboard automatically.", color = RadarMuted, fontSize = 12.sp)
        }
    }
}

package com.rideedge.app

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import java.io.File
import java.nio.ByteBuffer
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

internal interface AccessKeyStore {
    fun read(): String?
    fun write(value: String)
    fun clear()
}

/** AES key stays in Android Keystore; only authenticated ciphertext is saved.
 * No per-use unlock: an explicitly active car session must work with a locked
 * phone. This does not claim StrongBox backing or protection on a rooted phone.
 */
internal class AndroidAccessKeyStore(context: Context) : AccessKeyStore {
    private val file = AtomicFile(File(context.noBackupFilesDir, "rideedge-access.bin"))
    private val alias = "rideedge-access-v1"
    private val binding = RideEdgeConnection.origin.toByteArray(Charsets.UTF_8)

    private fun key(create: Boolean): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        check(create) { "Stored access key unavailable" }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setUserAuthenticationRequired(false).build())
        }.generateKey()
    }

    @Synchronized override fun read(): String? {
        if (!file.baseFile.exists()) return null
        return AccessKeyCipher.decrypt(file.readFully(), key(false), binding)
            .also { require(RideEdgeConnection.validKey(it)) }
    }

    @Synchronized override fun write(value: String) {
        require(RideEdgeConnection.validKey(value))
        val encrypted = AccessKeyCipher.encrypt(value, key(true), binding)
        val output = file.startWrite()
        try { output.write(encrypted); file.finishWrite(output) }
        catch (error: Exception) { file.failWrite(output); throw error }
    }

    @Synchronized override fun clear() { file.delete() }
}

internal object AccessKeyCipher {
    fun encrypt(value: String, key: SecretKey, binding: ByteArray): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key)
        cipher.updateAAD(binding)
        return byteArrayOf(1, cipher.iv.size.toByte()) + cipher.iv + cipher.doFinal(value.toByteArray(Charsets.UTF_8))
    }

    fun decrypt(value: ByteArray, key: SecretKey, binding: ByteArray): String {
        require(value.size in 30..256 && value[0] == 1.toByte() && value[1] == 12.toByte())
        val input = ByteBuffer.wrap(value, 2, value.size - 2)
        val iv = ByteArray(12).also(input::get)
        val encrypted = ByteArray(input.remaining()).also(input::get)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, iv))
        cipher.updateAAD(binding)
        return String(cipher.doFinal(encrypted), Charsets.UTF_8)
    }
}

internal object RideEdgeConnection {
    const val origin = BuildConfig.RIDEEDGE_ORIGIN
    fun validKey(value: String) = Regex("re_[A-Za-z0-9_-]{43}").matches(value)
    fun url(path: String): String {
        require(path.startsWith("/") && !path.startsWith("//") && !path.contains('\\'))
        return origin + path
    }
}

internal class AccessRequiredException(message: String) : IllegalStateException(message)

/** Explicit offline-preview diagnostic; never reads production app storage. */
internal fun checkPreviewAccessStorage(context: Context): String {
    check(BuildConfig.BUILD_TYPE == "preview")
    val store = AndroidAccessKeyStore(context)
    val fixture = "re_" + "s".repeat(43)
    return try {
        store.write(fixture)
        check(AndroidAccessKeyStore(context).read() == fixture)
        val file = File(context.noBackupFilesDir, "rideedge-access.bin")
        val encrypted = file.readBytes()
        check(!String(encrypted, Charsets.ISO_8859_1).contains(fixture))
        file.writeBytes(encrypted.copyOf().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() })
        check(runCatching { store.read() }.isFailure)
        "Android Keystore check passed · synthetic key, reopened storage, ciphertext and tamper rejection."
    } catch (_: Exception) {
        "Android Keystore check failed. Inspect the preview implementation before provisioning."
    } finally { store.clear() }
}

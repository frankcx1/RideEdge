package com.rideedge.app

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

internal object Edge {
    val Paper = Color(0xFF1F3A4D)
    val Card = Color(0xFF27455C)
    val Rule = Color(0xFF3D5F75)
    val Ink = Color(0xFFE9E4DA)
    val Soft = Color(0xFFB9C6D0)
    val Orange = Color(0xFFF08A3C)
    val Pressed = Color(0xFFF6A05C)
    val Blue = Color(0xFF9BC4DC)
    val Serif = FontFamily(Font(R.font.fraunces_650, FontWeight(650)))
    val Mono = FontFamily(Font(R.font.ibm_plex_mono_400), Font(R.font.ibm_plex_mono_600, FontWeight.SemiBold))
    val Heading = TextStyle(fontFamily = Serif, fontWeight = FontWeight(650), fontSize = 24.sp, color = Ink)
    val Meta = TextStyle(fontFamily = Mono, fontSize = 11.sp, lineHeight = 16.sp, color = Soft, fontFeatureSettings = "tnum")
    val Eyebrow = Meta.copy(fontWeight = FontWeight.SemiBold, fontSize = 10.5.sp, letterSpacing = 1.4.sp, color = Orange)
    val Prose = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 14.sp, lineHeight = 20.sp, color = Ink)
}

@Composable internal fun RideEdgeTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = darkColorScheme(
        primary = Edge.Orange, onPrimary = Edge.Paper, secondary = Edge.Blue, onSecondary = Edge.Paper,
        background = Edge.Paper, onBackground = Edge.Ink, surface = Edge.Card, onSurface = Edge.Ink,
        surfaceVariant = Edge.Paper, onSurfaceVariant = Edge.Soft, outline = Edge.Rule,
        error = Edge.Orange, onError = Edge.Paper,
    ), typography = Typography(
        headlineLarge = Edge.Heading.copy(fontSize = 34.sp), headlineMedium = Edge.Heading,
        titleLarge = Edge.Heading.copy(fontSize = 23.sp), titleMedium = Edge.Heading.copy(fontSize = 21.sp),
        titleSmall = Edge.Heading.copy(fontSize = 17.sp), bodyLarge = Edge.Prose,
        bodyMedium = Edge.Prose, bodySmall = Edge.Meta, labelLarge = Edge.Meta.copy(fontWeight = FontWeight.SemiBold, fontSize = 11.5.sp),
        labelMedium = Edge.Meta, labelSmall = Edge.Eyebrow,
    ), content = { EdgeExpansionProvider(content) })
}

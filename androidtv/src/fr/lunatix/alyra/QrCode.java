package fr.lunatix.alyra;

import java.nio.charset.StandardCharsets;

/**
 * Encodeur de QR code (mode octets, correction d'erreur M, versions 1 a 10), sans dependance.
 * Meme algorithme que la specification ISO 18004 ; le masque est fixe (0), ce qui suffit aux lecteurs.
 * Verifie module par module contre une implementation de reference (voir README).
 */
final class QrCode {
    private static final int[] ECC_PER_BLOCK_M = {-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26};
    private static final int[] BLOCKS_M = {-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5};
    private static final int MAX_VERSION = 10;

    final int size;
    final int version;
    private final boolean[][] modules;
    private final boolean[][] isFunction;

    /** @param mask masque 0..7 (0 par defaut ; les tests de comparaison en imposent un). */
    static QrCode encode(String text, int mask) {
        byte[] data = text.getBytes(StandardCharsets.UTF_8);
        int version = 1;
        while (true) {
            int capacityBits = numDataCodewords(version) * 8;
            int lengthBits = version < 10 ? 8 : 16;
            if (4 + lengthBits + data.length * 8 <= capacityBits) break;
            if (++version > MAX_VERSION) throw new IllegalArgumentException("Texte trop long pour le QR code");
        }
        return new QrCode(version, data, mask);
    }

    static QrCode encode(String text) { return encode(text, 0); }

    boolean get(int x, int y) { return x >= 0 && x < size && y >= 0 && y < size && modules[y][x]; }

    private QrCode(int version, byte[] data, int mask) {
        this.version = version;
        this.size = version * 4 + 17;
        modules = new boolean[size][size];
        isFunction = new boolean[size][size];

        drawFunctionPatterns();
        byte[] all = addEccAndInterleave(buildDataCodewords(version, data));
        drawCodewords(all);
        applyMask(mask);
        drawFormatBits(mask);
    }

    // ---- donnees ----------------------------------------------------------

    private static int numRawDataModules(int ver) {
        int result = (16 * ver + 128) * ver + 64;
        if (ver >= 2) {
            int numAlign = ver / 7 + 2;
            result -= (25 * numAlign - 10) * numAlign - 55;
            if (ver >= 7) result -= 36;
        }
        return result;
    }

    private static int numDataCodewords(int ver) {
        return numRawDataModules(ver) / 8 - ECC_PER_BLOCK_M[ver] * BLOCKS_M[ver];
    }

    private static byte[] buildDataCodewords(int ver, byte[] data) {
        int capacity = numDataCodewords(ver) * 8;
        boolean[] bits = new boolean[capacity];
        int n = 0;
        n = put(bits, n, 0x4, 4);                         // mode octets
        n = put(bits, n, data.length, ver < 10 ? 8 : 16); // longueur
        for (byte b : data) n = put(bits, n, b & 0xFF, 8);
        n = Math.min(n + 4, capacity);                    // terminateur (jusqu'a 4 zeros)
        n = (n + 7) / 8 * 8;                              // alignement sur l'octet
        byte[] out = new byte[capacity / 8];
        for (int i = 0; i < n; i++) if (bits[i]) out[i >>> 3] |= 1 << (7 - (i & 7));
        for (int i = n / 8, pad = 0xEC; i < out.length; i++, pad ^= 0xEC ^ 0x11) out[i] = (byte) pad;
        return out;
    }

    private static int put(boolean[] bits, int pos, int value, int len) {
        for (int i = len - 1; i >= 0; i--) bits[pos++] = ((value >>> i) & 1) != 0;
        return pos;
    }

    private byte[] addEccAndInterleave(byte[] data) {
        int numBlocks = BLOCKS_M[version];
        int blockEccLen = ECC_PER_BLOCK_M[version];
        int rawCodewords = numRawDataModules(version) / 8;
        int numShortBlocks = numBlocks - rawCodewords % numBlocks;
        int shortBlockLen = rawCodewords / numBlocks;

        byte[][] blocks = new byte[numBlocks][];
        byte[] div = rsDivisor(blockEccLen);
        for (int i = 0, k = 0; i < numBlocks; i++) {
            int datLen = shortBlockLen - blockEccLen + (i < numShortBlocks ? 0 : 1);
            byte[] dat = java.util.Arrays.copyOfRange(data, k, k + datLen);
            k += datLen;
            byte[] block = java.util.Arrays.copyOf(dat, shortBlockLen + 1);
            byte[] ecc = rsRemainder(dat, div);
            System.arraycopy(ecc, 0, block, block.length - blockEccLen, ecc.length);
            blocks[i] = block;
        }
        byte[] result = new byte[rawCodewords];
        for (int i = 0, k = 0; i < blocks[0].length; i++) {
            for (int j = 0; j < blocks.length; j++) {
                if (i != shortBlockLen - blockEccLen || j >= numShortBlocks) result[k++] = blocks[j][i];
            }
        }
        return result;
    }

    // ---- Reed-Solomon sur GF(256) -----------------------------------------

    private static byte[] rsDivisor(int degree) {
        byte[] result = new byte[degree];
        result[degree - 1] = 1;
        int root = 1;
        for (int i = 0; i < degree; i++) {
            for (int j = 0; j < degree; j++) {
                result[j] = (byte) mul(result[j] & 0xFF, root);
                if (j + 1 < degree) result[j] ^= result[j + 1];
            }
            root = mul(root, 0x02);
        }
        return result;
    }

    private static byte[] rsRemainder(byte[] data, byte[] divisor) {
        byte[] result = new byte[divisor.length];
        for (byte b : data) {
            int factor = (b ^ result[0]) & 0xFF;
            System.arraycopy(result, 1, result, 0, result.length - 1);
            result[result.length - 1] = 0;
            for (int i = 0; i < result.length; i++) result[i] ^= mul(divisor[i] & 0xFF, factor);
        }
        return result;
    }

    private static int mul(int x, int y) {
        int z = 0;
        for (int i = 7; i >= 0; i--) {
            z = (z << 1) ^ ((z >>> 7) * 0x11D);
            z ^= ((y >>> i) & 1) * x;
        }
        return z;
    }

    // ---- dessin -----------------------------------------------------------

    private void set(int x, int y, boolean dark) {
        modules[y][x] = dark;
        isFunction[y][x] = true;
    }

    private void drawFunctionPatterns() {
        for (int i = 0; i < size; i++) {
            set(6, i, i % 2 == 0);
            set(i, 6, i % 2 == 0);
        }
        finder(3, 3);
        finder(size - 4, 3);
        finder(3, size - 4);

        int[] pos = alignmentPositions();
        int n = pos.length;
        for (int i = 0; i < n; i++) {
            for (int j = 0; j < n; j++) {
                if ((i == 0 && j == 0) || (i == 0 && j == n - 1) || (i == n - 1 && j == 0)) continue;
                alignment(pos[i], pos[j]);
            }
        }
        drawFormatBits(0); // reserve la zone (reecrite avec le vrai masque)
        drawVersion();
    }

    private void finder(int cx, int cy) {
        for (int dy = -4; dy <= 4; dy++) {
            for (int dx = -4; dx <= 4; dx++) {
                int dist = Math.max(Math.abs(dx), Math.abs(dy));
                int x = cx + dx, y = cy + dy;
                if (x >= 0 && x < size && y >= 0 && y < size) set(x, y, dist != 2 && dist != 4);
            }
        }
    }

    private void alignment(int cx, int cy) {
        for (int dy = -2; dy <= 2; dy++)
            for (int dx = -2; dx <= 2; dx++) set(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) != 1);
    }

    private int[] alignmentPositions() {
        if (version == 1) return new int[0];
        int numAlign = version / 7 + 2;
        int step = (version * 4 + numAlign * 2 + 1) / (numAlign * 2 - 2) * 2;
        int[] result = new int[numAlign];
        result[0] = 6;
        for (int i = result.length - 1, pos = size - 7; i >= 1; i--, pos -= step) result[i] = pos;
        return result;
    }

    private void drawFormatBits(int mask) {
        int data = (0 << 3) | mask; // niveau M = 0
        int rem = data;
        for (int i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
        int bits = (data << 10 | rem) ^ 0x5412;
        for (int i = 0; i <= 5; i++) set(8, i, bit(bits, i));
        set(8, 7, bit(bits, 6));
        set(8, 8, bit(bits, 7));
        set(7, 8, bit(bits, 8));
        for (int i = 9; i < 15; i++) set(14 - i, 8, bit(bits, i));
        for (int i = 0; i < 8; i++) set(size - 1 - i, 8, bit(bits, i));
        for (int i = 8; i < 15; i++) set(8, size - 15 + i, bit(bits, i));
        set(8, size - 8, true);
    }

    private void drawVersion() {
        if (version < 7) return;
        int rem = version;
        for (int i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1F25);
        int bits = version << 12 | rem;
        for (int i = 0; i < 18; i++) {
            boolean color = bit(bits, i);
            int a = size - 11 + i % 3, b = i / 3;
            set(a, b, color);
            set(b, a, color);
        }
    }

    private static boolean bit(int x, int i) { return ((x >>> i) & 1) != 0; }

    private void drawCodewords(byte[] data) {
        int i = 0;
        for (int right = size - 1; right >= 1; right -= 2) {
            if (right == 6) right = 5;
            for (int vert = 0; vert < size; vert++) {
                for (int j = 0; j < 2; j++) {
                    int x = right - j;
                    boolean upward = ((right + 1) & 2) == 0;
                    int y = upward ? size - 1 - vert : vert;
                    if (!isFunction[y][x] && i < data.length * 8) {
                        modules[y][x] = bit(data[i >>> 3], 7 - (i & 7));
                        i++;
                    }
                }
            }
        }
    }

    private void applyMask(int mask) {
        for (int y = 0; y < size; y++) {
            for (int x = 0; x < size; x++) {
                boolean invert;
                switch (mask) {
                    case 0: invert = (x + y) % 2 == 0; break;
                    case 1: invert = y % 2 == 0; break;
                    case 2: invert = x % 3 == 0; break;
                    case 3: invert = (x + y) % 3 == 0; break;
                    case 4: invert = (x / 3 + y / 2) % 2 == 0; break;
                    case 5: invert = x * y % 2 + x * y % 3 == 0; break;
                    case 6: invert = (x * y % 2 + x * y % 3) % 2 == 0; break;
                    default: invert = ((x + y) % 2 + x * y % 3) % 2 == 0;
                }
                if (invert && !isFunction[y][x]) modules[y][x] = !modules[y][x];
            }
        }
    }
}

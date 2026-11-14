# Ghidra Reverse-Engineering Notes

This document describes the method used to analyze the native library of the camera vendor's Android application, and the Ghidra workflow. The protocol results derived from this analysis are in [protocol.md](protocol.md).

## Target

- File: `libobject_jni.so`, the arm64-v8a build extracted from the application package.
- Toolchain: Android NDK r17c, aarch64.
- The dynamic symbol table (`.dynsym`) contains about 5241 symbols. The `.symtab` section is absent or stripped, so most names come from the dynamic table.
- The library embeds the CS2 Network PPCS / PPPP stack (symbols `PPCS_*`, `cs2p2p_PPPP_*`, the `HLP2P_*` wrapper, and `VEEPAI_PktSend`).

## Method

1. **Symbol inventory.** List the dynamic symbols with `nm -D` and group them by component: P2P core, cipher, LAN discovery, license checks, JNI bridge, and the application layer (`CPPPPChannel`).
2. **Address mapping.** A Ghidra address equals the `nm -D` offset plus `0x100000`, the image base used when the library is imported. Addresses in these notes are Ghidra addresses unless stated otherwise.
3. **Decompilation.** Decompile each function of interest and record its behavior: constants, buffer layouts, and control flow. Table contents (the S-box and the CRC matrix) are read from memory and exported as binary files for offline testing.
4. **Byte-level cross-check.** Compare the decompiled output with the memory dumps byte by byte. For example, the CRC matrix was checked this way.
5. **Executable check.** Re-implement the algorithm in Python and test it. The cipher was checked with a round-trip test (1000 of 1000 inputs). A re-implementation is only a model until it is checked against real traffic.
6. **Traffic check.** Compare the re-implementation against a packet capture from the vendor's app and against a live camera on the LAN. Items that pass only the decompilation check remain marked [HYPOTHESIS] in protocol.md.

## Ghidra workflow

- Import `libobject_jni.so` as an ELF aarch64 binary and let the auto-analysis run. The machine used for the analysis had 8 cores and 15 GB of RAM.
- Use the symbol list from `nm -D` to find the functions by name. Many names in the dynamic table are exported C++ or C symbols, so the demangled form is used when searching.
- Read the function body in the decompiler window. Record the constants and the structure layout, then note the offset of each field.
- When a table is referenced, locate it at its data address and export the bytes. Name the exported files after their role (for example `p2p_sbox.bin` and `p2p_crc_matrix.bin`), not after the function that referenced them.
- Keep the address of every fact so that the claim can be checked again later.

## Limitations

- Decompiler line numbers are not stable across Ghidra versions. Refer to functions by name and address, not by line number.
- The decompiled code may hide the exact order of operations in optimized code. Such points are marked [HYPOTHESIS] until a test confirms them.
- Some functions named in the strings have not yet been decompiled. Their behavior is unknown, not inferred.

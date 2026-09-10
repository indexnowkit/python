# shellcheck shell=bash
# Sourced by the release scripts. The three names of a package (spec 26 §6): the short name is the tag prefix and the
# environment suffix (core@0.1.0, pypi-core), the distribution is the PyPI name (indexnowkit, indexnowkit-django), the
# directory under packages/ is the distribution. The core is the only package whose short name differs from its
# distribution; the others are indexnowkit-<short>.
dist_of() {
    case "$1" in
        core) printf 'indexnowkit' ;;
        *) printf 'indexnowkit-%s' "$1" ;;
    esac
}

short_of() {
    case "$1" in
        indexnowkit) printf 'core' ;;
        indexnowkit-*) printf '%s' "${1#indexnowkit-}" ;;
        *) printf '%s' "$1" ;;
    esac
}

# module name of a distribution: indexnowkit-django -> indexnowkit_django
module_of() {
    printf '%s' "${1//-/_}"
}

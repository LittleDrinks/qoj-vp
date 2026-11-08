# Prefer the packaged QOJ submit command in login shells.
if [ -x /usr/lib/qoj-vp/bin/submit ]; then
    case ":${PATH-}:" in
        *:/usr/lib/qoj-vp/bin:*) ;;
        *) PATH="/usr/lib/qoj-vp/bin${PATH:+:$PATH}" ;;
    esac
    export PATH
fi

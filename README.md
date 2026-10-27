    # SigmaOS-chatroom

    LAN chat server & client

    Part of the **SigmaOS** sovereign operating-system ecosystem — a multi-repository
    distribution modelled on Linux Mint and Omarchy Linux. See the parent
    [`SigmaOS`](https://github.com/AaryanSinghChauhan09/SigmaOS) repository for the
    full component index.

    ## Upstream inspirations
    - https://github.com/linuxmint/jargonaut

    ## Design principles applied
    - **Abstraction**
- **Separation of Concerns**
- **Fail-Fast**
- **KISS**
- **Deterministic Testing**
- **Information Hiding**

    ## Usage
    Verbs: `serve-plan, rooms, users, broadcast-plan`

    ```
    $ sigma-chat serve-plan --port 6667
$ sigma-chat rooms
$ sigma-chat users
$ sigma-chat broadcast-plan --user alice --text "hello" --kind room

    ```

    ## Build & test
    ```
    make build
    make test
    ```

    ## Licence
    GNU General Public License v3.0 (FOSS).

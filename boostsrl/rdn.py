# Copyright © 2017, 2018, 2019 Alexander L. Hayes

"""
Relational Dependency Networks
"""

import re
import numpy as np

from .base import BaseBoostedRelationalModel

# TODO: @property: feature_importances_


class RDN(BaseBoostedRelationalModel):
    """Relational Dependency Networks Estimator

    Wrappers around BoostSRL for learning and inference with Relational Dependency
    Networks written with a scikit-learn-style interface derived from
    :class:`sklearn.base.BaseEstimator`

    Similar to :class:`sklearn.ensemble.GradientBoostingClassifier`, this builds
    a model by fitting a series of regression trees.

    Examples
    --------

    >>> from boostsrl.rdn import RDN
    >>> from boostsrl import Background
    >>> from boostsrl import example_data
    >>> bk = Background(modes=example_data.train.modes, use_std_logic_variables=True)
    >>> dn = RDN(background=bk, target="cancer")
    >>> dn.fit(example_data.train)
    RDN(background=setParam: nodeSize=2.
    setParam: maxTreeDepth=3.
    setParam: numberOfClauses=100.
    setParam: numberOfCycles=100.
    useStdLogicVariables: true.
    mode: friends(+Person,-Person).
    mode: friends(-Person,+Person).
    mode: smokes(+Person).
    mode: cancer(+Person).
    ,
        max_tree_depth=3, n_estimators=10, node_size=2, target='cancer')
    >>> dn.predict(example_data.test)
    array([ True,  True,  True, False, False])

    """

    # pylint: disable=too-many-instance-attributes

    def __init__(
        self,
        background=None,
        target="None",
        n_estimators=10,
        node_size=2,
        max_tree_depth=3,
    ):
        """Initialize an RDN

        Parameters
        ----------
        background : :class:`boostsrl.background.Background` (default: None)
            Background knowledge with respect to the database
        target : str (default: "None")
            Target predicate to learn
        n_estimators : int, optional (default: 10)
            Number of trees to fit
        node_size : int, optional (default: 2)
            Maximum number of literals in each node.
        max_tree_depth : int, optional (default: 3)
            Maximum number of nodes from root to leaf (height) in the tree.

        Attributes
        ----------
        estimators_ : array, shape (n_estimators)
            Return the boosted regression trees
        feature_importances_ : array, shape (n_features)
            Return the feature importances (based on how often each feature appears)
        """

        super().__init__(
            background=background,
            target=target,
            n_estimators=n_estimators,
            node_size=node_size,
            max_tree_depth=max_tree_depth,
        )

    def fit(self, database):
        """Learn structure and parameters.

        Fit the structure and parameters of a Relational Dependency Network using a
        database of positive examples, negative examples, facts, and any relevant
        background knowledge.

        Parameters
        ----------
        database : :class:`boostsrl.database.Database`
            Database containing examples and facts.

        Returns
        -------
        self : object
            Returns self.

        Notes
        -----

        The underlying algorithm is based on the "Relational Functional Gradient
        Boosting" as described in [1]_.

        This fit function is based on subprocess calling the BoostSRL jar files.
        This will require a Java runtime to also be available. See [2]_.

        .. [1] Sriraam Natarajan, Tushar Khot, Kristian Kersting, and Jude Shavlik,
           "*Boosted Statistical Relational Learners: From Benchmarks to Data-Driven
           Medicine*". SpringerBriefs in Computer Science, ISBN: 978-3-319-13643-1,
           2015
        .. [2] https://starling.utdallas.edu/software/boostsrl/
        """

        self._check_params()

        # Write the background to file.
        self.background.write(
            filename="train", location=self.file_system.files.TRAIN_DIR.value
        )

        # Write the data to files.
        database.write(
            filename="train", location=self.file_system.files.TRAIN_DIR.value
        )

        _CALL = (
            "java -jar "
            + str(self.file_system.files.BOOST_JAR.value)
            + " -l -train "
            + str(self.file_system.files.TRAIN_DIR.value)
            + " -target "
            + self.target
            + " -trees "
            + str(self.n_estimators)
            + " > "
            + str(self.file_system.files.TRAIN_LOG.value)
        )

        if self.debug:
            print(_CALL)

        # Call the constructed command.
        self._call_shell_command(_CALL)

        # Read the trees from files.
        _estimators = []
        for _tree_number in range(self.n_estimators):
            with open(
                self.file_system.files.TREES_DIR.value.joinpath(
                    "{0}Tree{1}.tree".format(self.target, _tree_number)
                )
            ) as _fh:
                _estimators.append(_fh.read())

        self.estimators_ = _estimators

        # TODO: On error, collect log files.
        return self

    # TODO: This may be possible to set in the base class.
    def _run_inference(self, database) -> None:
        """Run inference mode on the BoostSRL Jar files.

        This is a helper method for ``self.predict`` and ``self.predict_proba``
        """

        self._check_initialized()

        # Write the background to file.
        self.background.write(
            filename="test", location=self.file_system.files.TEST_DIR.value
        )

        # Write the data to files.
        database.write(filename="test", location=self.file_system.files.TEST_DIR.value)

        _CALL = (
            "java -jar "
            + str(self.file_system.files.BOOST_JAR.value)
            + " -i -test "
            + str(self.file_system.files.TEST_DIR.value)
            + " -model "
            + str(self.file_system.files.MODELS_DIR.value)
            + " -target "
            + self.target
            + " -trees "
            + str(self.n_estimators)
            + " -aucJarPath "
            + str(self.file_system.files.AUC_JAR.value)
            + " > "
            + str(self.file_system.files.TEST_LOG.value)
        )

        if self.debug:
            print(_CALL)

        self._call_shell_command(_CALL)

        # Read the threshold
        with open(self.file_system.files.TEST_LOG.value, "r") as _fh:
            _threshold = re.findall("% Threshold = \\d*.\\d*", _fh.read())
        self.threshold_ = float(_threshold[0].split(" = ")[1])

    def predict(self, database):
        """Use the learned model to predict on new data.

        Parameters
        ----------
        database : :class:`boostsrl.Database`
            Database containing examples and facts.

        Returns
        -------
        results : ndarray
            Positive or negative class.
        """

        self._run_inference(database)

        # Collect the classifications.
        _results_db = self.file_system.files.TEST_DIR.value.joinpath(
            "results_" + self.target + ".db"
        )
        _classes, _results = np.loadtxt(
            _results_db,
            delimiter=" ",
            usecols=(0, 1),
            converters={0: lambda s: 0 if s[0] == 33 else 1},
            unpack=True,
        )

        self.classes_ = _classes

        _neg = _results[_classes == 0]
        _pos = _results[_classes == 1]
        _results2 = np.greater(
            np.concatenate((_pos, 1 - _neg), axis=0), self.threshold_
        )

        return _results2

    def predict_proba(self, database):
        """Return class probabilities.

        Parameters
        ----------
        database : :class:`boostsrl.Database`
            Database containing examples and facts.

        Returns
        -------
        results : ndarray
            Probability of belonging to the positive class
        """

        self._run_inference(database)

        _results_db = self.file_system.files.TEST_DIR.value.joinpath(
            "results_" + self.target + ".db"
        )
        _classes, _results = np.loadtxt(
            _results_db,
            delimiter=" ",
            usecols=(0, 1),
            converters={0: lambda s: 0 if s[0] == 33 else 1},
            unpack=True,
        )

        _neg = _results[_classes == 0]
        _pos = _results[_classes == 1]
        _results2 = np.concatenate((_pos, 1 - _neg), axis=0)

        self.classes_ = _classes

        return _results2

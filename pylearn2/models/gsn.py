"""
Generative Stochastic Networks

This is described in:
- "Generalized Denoising Auto-Encoders as Generative Models" Bengio, Yao, Alain,
   Vincent. arXiv:1305.6663
- "Deep Generative Stochastic Networks Trainable by Backprop" Bengio,
   Thibodeau-Laufer. arXiv:1306.1091
"""
__authors__ = "Eric Martin"
__copyright__ = "Copyright 2013, Universite de Montreal"
__license__ = "3-clause BSD"

import functools

import theano.tensor as T

import pylearn2
from pylearn2.base import StackedBlocks
from pylearn2.corruption import BinomialSampler, ComposedCorruptor,\
                                MultinomialSampler
from pylearn2.models.autoencoder import Autoencoder
from pylearn2.models.model import Model

class GSN(StackedBlocks, Model):
    def __init__(self, autoencoders, preact_cors=None, postact_cors=None,
                 layer_samplers=None):
        """
        Initialize an Generative Stochastic Network (GSN) object.

        Parameters
        ----------
        autoencoders : list
            A list of autoencoder objects. As of now, only the functionality
            from the base Autoencoder class is used.
        preact_cors : list
            A list of length len(autoencoders) + 1 where each element is a
            callable (which includes Corruptor objects). The callable at index
            i is called before activating the ith layer. Name stands for
            "preactivation corruptors".
            Valid values: None or list of length len(autoencoders) + 1. If the
            list contains a non-callable corruptor for a layer, then no
            corruption function is applied for that layer.
        postact_cors : list
            A list of length len(autoencoders) + 1 where each element is a
            callable (which includes Corruptor objects). The callable at index
            i is called directly after activating the ith layer. Name stands for
            "postactivation corruptors".
            The valid values for this parameter are the same as that for
            preact_cors.
        layer_samplers: list
            Describes how to sample from each layer. Sampling occurs directly
            before the post activation corruption is applied.
            Valid values for this argument are of the same form as valid parameters
            for preact_cor and postact_cor (and if an element in the list is None,
            no sampling will be applied at that layer). Note: as of right now,
            we've only experimented with sampling at the visible layer.

        Notes
        -----
        Most of the time it will be much easier to construct a GSN using GSN.new
        rather than GSN.__init__. This method exists to make the GSN class very
        easy to modify.
        The activation function for the visible layer is the "act_dec"
        function on the first autoencoder, and the activation function for the ith
        hidden layer is the "act_enc" function on the (i - 1)th autoencoder.
        """
        super(GSN, self).__init__(autoencoders)

        # only for convenience
        self.aes = self._layers

        for i, ae in enumerate(self.aes):
            if i != 0:
                if ae.weights is None:
                    ae.set_visible_size(self.aes[i - 1].nhid)
                else:
                    assert (ae.weights.get_value().shape[0] ==
                            self.aes[i - 1].nhid)

        def _make_callable_list(previous):
            num_activations = len(self.aes) + 1
            identity = pylearn2.utils.identity
            if previous is None:
                previous = [identity] * num_activations

            assert len(previous) == num_activations

            for i, f in enumerate(previous):
                if not callable(f):
                    previous[i] = identity
            return previous

        self._preact_cors = _make_callable_list(preact_cors)
        self._postact_cors = _make_callable_list(postact_cors)

        if layer_samplers is not None:
            assert len(layer_samplers) == len(self.postact_cors)
            for i, sampler in enumerate(layer_samplers):
                if callable(sampler):
                    self.postact_cors[i] = ComposedCorruptor(
                        self.postact_cors[i],
                        layer_samplers[i]
                    )

    @staticmethod
    def _make_aes(layer_sizes, activation_funcs, tied=True):
        aes = []
        assert len(activation_funcs) == len(layer_sizes)

        for i in xrange(len(layer_sizes) - 1):
            # activation for visible layer is aes[0].act_dec
            act_enc = activation_funcs[i + 1]
            act_dec = act_enc if i != 0 else activation_funcs[0]
            aes.append(
                Autoencoder(layer_sizes[i], layer_sizes[i + 1],
                            act_enc, act_dec, tied_weights=tied)
            )

        return aes

    @classmethod
    def new(cls,
            layer_sizes,
            activation_funcs,
            pre_corruptors,
            post_corruptors,
            layer_samplers):

        aes = cls._make_aes(layer_sizes, activation_funcs)

        return cls(aes,
                   preact_cors=pre_corruptors,
                   postact_cors=post_corruptors,
                   layer_samplers=layer_samplers)

    @classmethod
    def new_ae_gsn(cls, layer_sizes, vis_corruptor=None, hidden_pre_corruptor=None,
                   hidden_post_corruptor=None, visible_act="sigmoid",
                   hidden_act="tanh"):
        """
        This is just a convenience method to initialize GSN instances. The
        __init__ method is far more general, but this should capture most
        of the GSN use cases.

        Note
        ----
        This is used only for the autoencoder like GSNs described in the papers
        referenced above. GSNs for supervised learning should not use this
        method.

        Parameters
        ----------
        layer_sizes : list of integers
            Each element of this list states the size of a layer in the GSN. The
            first element in this list is the size of the visual layer.
        vis_corruptor : callable
            A callable object (such as a Corruptor) that is used to corrupt the
            visible layer.
        hidden_pre_corruptor : callable
            Same sort of object as the vis_corruptor, used to corrupt (add noise)
            the top hidden activations prior to activation.
        hidden_post_corruptor : callable
            Same sort of object as the other corruptors, used to corrupt top
            hidden activation after activation.
        visible_act : callable or string
            The value for visible_act must be a valid value for the act_dec
            parameter of Autoencoder.__init__
        hidden_act : callable or string
            The value for visible_act must be a valid value for the act_enc
            parameter of Autoencoder.__init__
        """
        activations = [visible_act] + [hidden_act] * (len(self.layers) - 1)

        pre_corruptors = [None] * len(aes) + [hidden_pre_corruptor]
        post_corruptors = [vis_corruptor] + None * (len(aes) - 1) +\
            [hidden_post_corruptor]

        # binomial sampling on visible layer by default
        layer_samplers = [BinomialSampler()] + [None] * len(aes)

        return cls.new(layer_sizes, activations, pre_corruptors, post_corruptors,
                       layer_samplers)

    @functools.wraps(Model.get_params)
    def get_params(self):
        params = []
        for ae in self.aes:
            params.extend(ae.get_params())
        return params

    def _run(self, minibatch, walkback=0, clamped=None, sparse=sparse):
        """
        This runs the GSN on input 'minibatch' are returns all of the activations
        at every time step.

        Parameters
        ----------
        minibatch : tensor_like or list of tensor_likes
            Theano symbolic representing the input minibatch.
        walkback : int
            How many walkback steps to perform.
        clamped : tensor_like
            A theano matrix that is 1 at all indices where the visible layer
            should be kept constant and 0 everywhere else. If no indices are
            going to be clamped, its faster to keep clamped as None rather
            than set it to the 0 matrix.

        Returns
        ---------
        steps : list of list of tensor_likes
            A list of the activations at each time step. The activations
            themselves are lists of tensor_like symbolic (shared) variables.
            A time step consists of a call to the _update function (so updating
            both the odd and even layers).

            This overwrites self._activation_history
        """
        self._set_activations(minibatch, sparse=sparse)

        # FIXME: extend clamping for multiple values with costs
        if clamped is not None:
            clamped_vals = minibatch * clamped
            unclamped = T.eq(clamped, 0)

        # intialize steps
        steps = [self.activations[:]]

        for time in xrange(1, len(self.aes) + walkback + 1):
            self._update(self.activations)

            if clamped is not None:
                self.activations[0] = (self.activations[0] * unclamped
                                       + clamped_vals)

            # slicing makes a shallow copy
            steps.append(self.activations[:])

            # Apply post activation corruption to even layers
            evens = xrange(0, len(self.activations), 2)
            self._apply_postact_corruption(self.activations, evens)

        self._activation_history = steps
        return steps

    def get_samples(self, minibatch, walkback=0, indices=None, fresh=True):
        """
        Runs minibatch through GSN and returns reconstructed data.

        Parameters
        ----------
        minibatch : tensor_like
            Theano symbolic representing the input minibatch.
        walkback : int
            How many walkback steps to perform. This is both how many extra
            samples to take as well as how many extra reconstructed points
            to train off of.
        fresh : bool
            Indicates whether or not the minibatch should be ran through
            the network or existing activations should be used. Generally
            fresh should be True, unless you want to call get_samples and
            some other function of the activation history for the same minibatch.

        Returns
        ---------
        reconstructions : list of tensor_likes
            A list of length 1 + walkback that contains the samples generated
            by the GSN. The samples will be of the same size as the minibatch.
        """
        # by default just get the first (bottom) layer
        if indices is None:
            indices = [0]

        if fresh:
            results = self._run(minibatch, walkback=walkback)
        else:
            results = self._activation_history

        # leave out the first time step
        activations = results[1:]

        return [[act[i] for i in indices] for act in activations]

    @functools.wraps(Autoencoder.reconstruct)
    def reconstruct(self, minibatch, fresh=True):
        # included for compatibility with cost functions for autoencoders
        return self.get_samples(minibatch, walkback=0, fresh=fresh,
                                indices=[0])[0]

    def __call__(self, minibatch):
        """
        As specified by StackedBlocks, this returns the output representation of
        all layers. This occurs at the final time step.
        """
        return self._run(minibatch)[-1]

    """
    NOTE: The following methods contain the algorithmic content of the GSN class.
    All of these methods are written in a way such that they can be run without
    modifying the state of the GSN object. This primary visible consequence of this
    is that the methods take an "activations parameter", which is generally just
    self.activations.
    Although this style is a bit odd, it is completely necessary. Theano can handle
    small amounts of walkback (which allows us to train for walkback), but for
    many sampling iterations (ie more than 10) Theano takes an extremely long time
    to compile these large computational graphs. Making all of these methods
    take activations as an explicit parameter (which they then modify in place,
    which allows calling with self.activations) allows one to create smaller
    external Theano functions that allow many sampling iterations.
    See pylearn2.models.tests.test_gsn.sampling_test for an example.
    """

    def _set_activations(self, minibatch, set_val=True, sparse=True):
        """
        Sets the input layer to minibatch and all other layers to 0.

        Parameters:
        ------------
        minibatch : tensor_like or list of (int, tensor_like)
            Theano symbolic representing the input minibatch. See
            description for sparse parameter.
        set_val : bool
            Determines whether the method sets self.activations.
        sparse : bool
            Indicates whether minibatch is a sparse list of activations
            or a dense list. If sparse is true, then the minibatch
            parameter must be a list of tuples of form (int, tensor_like),
            where the int component represents the index of the layer
            (so 0 for visible, -1 for top/last layer) and the tensor_like
            represents the activation at that level. Components not included
            in the sparse activations will be set to 0.
            If sparse if false, then the input must be a list of length
            equal to the number of layers (visible included) of the network.
            When sparse is false, each element in the list must either be
            a tensor_like or None (items that are None will be set to 0's).
        Note
        ----
        This method creates a new list, not modifying an existing list.
        """

        if sparse:
            activations = [None] * (len(self.aes) + 1)
            indices = [t[0] for t in minibatch]
            for i, val in minibatch:
                activations[i] = val
        else:
            assert len(minibatch) == (len(self.aes) + 1)
            activations = minibatch[:]
            indices = filter(lambda i: activations[i] is not None, xrange(len(activations)))

        # this shouldn't be strictly necessary, but the algorithm is much easier if the
        # first activation is always set. This code should be restructured if someone
        # wants to run this without setting the first activation (because the for loop
        # below assumes that the first activation is non-None

        assert activations[0] is not None
        for i in xrange(1, len(activations)):
            if activations[i] is None:
                activations[i] = T.zeros_like(
                    T.dot(activations[i - 1], self.aes[i - 1].weights)
                )

        # corrupt the input
        activations = self._apply_postact_cors(self.activations, indices)

        if set_val:
            self.activations = activations

        return activations

    def _update(self, activations):
        """
        See Figure 1 in "Deep Generative Stochastic Networks as Generative
        Models" by Bengio, Thibodeau-Laufer.
        This and _update_activations implement exactly that, which is essentially
        forward propogating the neural network in both directions.

        Parameters
        ----------
        old_activations : list of tensors
            This parameter should not be used during training. This exists so that
            many iterations of sampling can be done without having to build a huge
            Theano computation graph.
        """
        # Update and corrupt all of the odd layers
        odds = range(1, len(activations), 2)
        self._update_activations(activations, odds)
        self._apply_postact_corruption(activations, odds)

        # Update the even layers. Not applying post activation noise now so that
        # that cost function can be evaluated
        evens = xrange(0, len(activations), 2)
        self._update_activations(activations, evens)

        return activations

    @staticmethod
    def _apply_corruption(activations, corruptors, idx_iter):
        """
        Applies post activation corruption to layers.

        Parameters
        ----------
        activations : list of tensor_likes
            Generally gsn.activations
        corruptors : list of callables
            Generally gsn.postact_cors or gsn.preact_cors
        idx_iter : iterable
            An iterable of indices into self.activations. The indexes indicate
            which layers the post activation corruptors should be applied to.
        """
        assert len(corruptors) == len(activations)
        for i in idx_iter:
            activations[i] = corruptors[i](activations[i])
        return activations

    def apply_preact_corruption(self, activations, idx_iter):
        return self._apply_corruption(activations, self._preact_cors,
                                      idx_iter)

    def apply_postact_corruption(self, activations, idx_iter):
        return self._apply_corruption(activations, self._postact_cors,
                                      idx_iter)

    def _update_activations(self, activations, idx_iter):
        """
        Parameters
        ----------
        idx_iter : iterable
            An iterable of indices into self.activations. The indexes indicate
            which layers should be updated.
            Must be able to iterate over idx_iter multiple times.
        """
        from_above = lambda i: (self.aes[i].visbias +
                                T.dot(activations[i + 1],
                                      self.aes[i].w_prime))

        from_below = lambda i: (self.aes[i - 1].hidbias +
                                T.dot(activations[i - 1],
                                     self.aes[i - 1].weights))

        for i in idx_iter:
            # first compute then hidden activation
            if i == 0:
                activations[i] = from_above(i)
            elif i == len(activations) - 1:
                activations[i] = from_below(i)
            else:
                activations[i] = from_below(i) + from_above(i)

        self._apply_preact_corruption(self.activations, idx_iter)

        for i in idx_iter:
            # Using the activation function from lower autoencoder
            act_func = None
            if i == 0:
                act_func = self.aes[0].act_dec
            else:
                act_func = self.aes[i - 1].act_enc

            # ACTIVATION
            # None implies linear
            if act_func is not None:
                activations[i] = act_func(activations[i])
